import json
import boto3
import base64
import os
import uuid
import time
import urllib.parse

# Initialize AWS clients outside the handler for potential reuse
s3_client = boto3.client('s3')
transcribe_client = boto3.client('transcribe')
bedrock_runtime = boto3.client('bedrock-runtime')
polly_client = boto3.client('polly')

# --- Configuration (Retrieve from Environment Variables) ---
# Make sure to set these in the Lambda function's configuration!
AUDIO_OUTPUT_BUCKET = os.environ.get('AUDIO_OUTPUT_BUCKET', 'via-assistant-private-audio') # Replace default if needed
TEMP_UPLOAD_BUCKET = os.environ.get('TEMP_UPLOAD_BUCKET', 'via-assistant-temp-upload-bucket') # Can use the same bucket or a different one
TEMP_UPLOAD_PREFIX = os.environ.get('TEMP_UPLOAD_PREFIX', 'temp-uploads/') # Folder within the bucket for uploads
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'anthropic.claude-3-haiku-20240307-v1:0') # Example: Claude 3 Haiku
POLLY_VOICE_ID = os.environ.get('POLLY_VOICE_ID', 'Joanna') # Example: Joanna (Neural)
POLLY_ENGINE = os.environ.get('POLLY_ENGINE', 'neural')
PRESIGNED_URL_EXPIRY = int(os.environ.get('PRESIGNED_URL_EXPIRY', 300)) # Default: 5 minutes

def lambda_handler(event, context):
    """
    Main Lambda handler function triggered by API Gateway.
    Orchestrates STT -> LLM -> TTS -> S3 Pre-signed URL generation.
    """
    print("Received event:", json.dumps(event)) # Log the incoming event for debugging

    try:
        # 1. Get Audio Data from the request
        # Assuming API Gateway is proxying and the frontend sends base64 encoded audio in the body
        if not event.get('body'):
             raise ValueError("Missing 'body' in the request event.")

        # Decode Base64 audio data
        # Check if the event body is already base64 decoded by API Gateway (depends on config)
        if event.get('isBase64Encoded', False):
            audio_bytes = base64.b64decode(event['body'])
            print(f"Decoded base64 audio. Size: {len(audio_bytes)} bytes")
        else:
             # If not base64 encoded, assume it's raw binary or needs different handling
             # For simplicity, this example assumes base64 encoding from the frontend/API Gateway
             # If sending raw binary, adjustments might be needed here and in API Gateway settings.
             # Let's try decoding anyway, sometimes API Gateway might not set the flag correctly
             try:
                 audio_bytes = base64.b64decode(event['body'])
                 print(f"Decoded base64 audio (flag was false/missing). Size: {len(audio_bytes)} bytes")
             except (TypeError, ValueError):
                 print("Body doesn't seem to be base64 encoded, attempting to use as raw bytes (if applicable)")
                 # If your API Gateway/frontend sends raw binary, you might use event['body'] directly
                 # However, raw binary handling via API Gateway JSON payload can be tricky. Base64 is safer.
                 # For this example's flow, we'll proceed assuming it *should* be base64 for the upload step.
                 # If it fails here, the upload will likely fail. Consider sending raw binary directly to S3
                 # from the frontend if base64 causes issues (more complex frontend code).
                 # Re-raising for clarity in this example if decoding fails after trying:
                 raise ValueError("Could not decode base64 audio data from request body.")


        if not audio_bytes:
             raise ValueError("Decoded audio data is empty.")

        # Generate unique names for temporary files/jobs
        job_id = str(uuid.uuid4())
        temp_s3_key = f"{TEMP_UPLOAD_PREFIX}{job_id}.wav" # Assuming WAV format from frontend, adjust if needed

        # --- 2. Upload audio to temporary S3 location for Transcribe ---
        print(f"Uploading received audio to s3://{TEMP_UPLOAD_BUCKET}/{temp_s3_key}")
        s3_client.put_object(
            Bucket=TEMP_UPLOAD_BUCKET,
            Key=temp_s3_key,
            Body=audio_bytes
        )
        temp_s3_uri = f"s3://{TEMP_UPLOAD_BUCKET}/{temp_s3_key}"
        print(f"Audio uploaded successfully to {temp_s3_uri}")


        # --- 3. Start Transcription Job ---
        # Assuming WAV/MP3/FLAC/Opus etc. Transcribe will try to auto-detect.
        # Specify MediaFormat if known & needed.
        transcribe_job_name = f"via-transcription-{job_id}"
        transcript_output_key = f"transcripts/{transcribe_job_name}.json"
        print(f"Starting transcription job: {transcribe_job_name}")
        transcribe_client.start_transcription_job(
            TranscriptionJobName=transcribe_job_name,
            LanguageCode='en-US',  # Adjust language code if needed
            Media={'MediaFileUri': temp_s3_uri},
            OutputBucketName=TEMP_UPLOAD_BUCKET, # Should use the variable
            OutputKey=transcript_output_key     # Should use the variable}
            # Add MediaFormat='wav' (or mp3, ogg, etc.) if auto-detection fails
        )

        # --- 4. Poll for Transcription Job Completion ---
        # WARNING: Polling within a single Lambda invocation is simple but can be inefficient
        # and might hit Lambda timeouts for long audio. Event-driven approach (S3 Event -> Lambda -> Transcribe -> EventBridge -> Lambda)
        # is better for production but more complex to set up initially.
        transcript_text = ""
        max_attempts = 20 # Approx 1 minute with 3 sec wait
        attempts = 0
        print("Polling for transcription job completion...")
        while attempts < max_attempts:
            attempts += 1
            job_status = transcribe_client.get_transcription_job(TranscriptionJobName=transcribe_job_name)
            status = job_status['TranscriptionJob']['TranscriptionJobStatus']
            print(f"Attempt {attempts}: Job status = {status}")

            if status == 'COMPLETED':
                transcript_uri = job_status['TranscriptionJob']['Transcript']['TranscriptFileUri']
                # Download transcript file from S3

                #transcript_response = s3_client.get_object(Bucket=urllib.parse.urlparse(transcript_uri).netloc, Key=urllib.parse.urlparse(transcript_uri).path.lstrip('/'))
                transcript_response = s3_client.get_object(
                    Bucket=TEMP_UPLOAD_BUCKET, # Uses the variable
                    Key=transcript_output_key  # Uses the variable
                )
                transcript_data = json.loads(transcript_response['Body'].read().decode('utf-8'))
                transcript_text = transcript_data['results']['transcripts'][0]['transcript']
                print(f"Transcription complete: {transcript_text}")
                break
            elif status == 'FAILED':
                print(f"Transcription job failed: {job_status['TranscriptionJob'].get('FailureReason', 'Unknown reason')}")
                raise Exception(f"Transcription failed: {job_status['TranscriptionJob'].get('FailureReason', 'Unknown reason')}")

            time.sleep(3) # Wait before polling again

        if not transcript_text:
             raise TimeoutError("Transcription job did not complete in time.")

        # --- (Optional) Delete temporary S3 audio file ---
        try:
            print(f"Deleting temporary file: s3://{TEMP_UPLOAD_BUCKET}/{temp_s3_key}")
            s3_client.delete_object(Bucket=TEMP_UPLOAD_BUCKET, Key=temp_s3_key)
        except Exception as e:
            print(f"Warning: Failed to delete temporary S3 file {temp_s3_key}. Error: {e}") # Log error but continue

        # --- (Optional) Delete transcription job ---
        # Note: Completed jobs are often kept for history, but can be deleted to clean up.
        try:
            print(f"Deleting transcription job: {transcribe_job_name}")
            transcribe_client.delete_transcription_job(TranscriptionJobName=transcribe_job_name)
        except Exception as e:
             print(f"Warning: Failed to delete transcription job {transcribe_job_name}. Error: {e}")


        # --- 5. Send transcript to Bedrock (LLM) ---
        print(f"Sending transcript to Bedrock model: {BEDROCK_MODEL_ID} using Messages API format")

        # Construct the system prompt (defines the AI's persona and instructions)
        system_prompt = "You are Via, a friendly, patient, and clear virtual tech voice assistant helping senior citizens. Answer the user's technology question simply and step-by-step if possible. Avoid jargon. Keep responses concise but helpful."

        # Construct the messages array
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": transcript_text # The user's transcribed question
                    }
                ]
            }
        ]

        # Note: For Claude 3, max_tokens refers to the max output tokens.
        # It doesn't use "max_tokens_to_sample" like older Claude models.
        request_body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31", # Required for Claude 3 Messages API
            "max_tokens": 1024, # Maximum number of tokens to generate in the response
            "system": system_prompt,
            "messages": messages,
            "temperature": 0.7,
            # "top_p": 0.9, # Optional: Add other parameters as needed
            # "top_k": 50,  # Optional
        })

        print("Bedrock Request Body:", request_body) # Log the request body for debugging

        bedrock_response = bedrock_runtime.invoke_model(
            body=request_body,
            modelId=BEDROCK_MODEL_ID,
            accept='application/json',
            contentType='application/json'
        )

        response_body = json.loads(bedrock_response['body'].read())
        print("Bedrock Raw Response Body:", response_body) # Log the raw response

        # --- For Claude 3 Messages API, the response structure is different ---
        # The response is in response_body['content'][0]['text']
        if response_body.get("content") and isinstance(response_body["content"], list) and len(response_body["content"]) > 0:
            llm_response_text = response_body["content"][0].get("text")
        else:
            print("Error: 'content' not found or not in expected format in Bedrock response:", response_body)
            llm_response_text = None # Or raise an error

        if not llm_response_text:
             # Check for error messages from Bedrock
             if response_body.get("type") == "error":
                  error_details = response_body.get("error", {})
                  error_message = error_details.get("message", "Unknown Bedrock error")
                  print(f"Bedrock API returned an error: {error_message}")
                  raise ValueError(f"Bedrock error: {error_message}")
             raise ValueError("Failed to get completion text from Bedrock Messages API response or response format unexpected.")

        print(f"Bedrock response received (Messages API): {llm_response_text[:100]}...")


        # --- 6. Synthesize LLM response to Speech using Polly ---
        print(f"Synthesizing text to speech using Polly voice: {POLLY_VOICE_ID}")
        polly_response = polly_client.synthesize_speech(
            Text=llm_response_text,
            OutputFormat='mp3',
            VoiceId=POLLY_VOICE_ID,
            Engine=POLLY_ENGINE
        )

        # --- 7. Upload Polly audio output to S3 ---
        audio_output_key = f"via-responses/{str(uuid.uuid4())}.mp3"
        print(f"Uploading Polly audio output to s3://{AUDIO_OUTPUT_BUCKET}/{audio_output_key}")
        s3_client.put_object(
            Bucket=AUDIO_OUTPUT_BUCKET,
            Key=audio_output_key,
            Body=polly_response['AudioStream'].read(),
            ContentType='audio/mpeg' # Important for playback
        )

        # --- 8. Generate Pre-signed URL for the audio output ---
        print(f"Generating pre-signed URL for s3://{AUDIO_OUTPUT_BUCKET}/{audio_output_key}")
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': AUDIO_OUTPUT_BUCKET, 'Key': audio_output_key},
            ExpiresIn=PRESIGNED_URL_EXPIRY
        )
        print(f"Pre-signed URL generated: {presigned_url[:100]}...")


        # --- 9. Format and Return Response for API Gateway ---
        response_payload = {
            'transcript': llm_response_text, # Return the LLM's response text
            'audioUrl': presigned_url
        }

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*', # Required for CORS from browser
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'OPTIONS,POST'
            },
            'body': json.dumps(response_payload)
        }

    except Exception as e:
        print(f"Error processing request: {e}")
        # Attempt to clean up temporary S3 file if it exists and job started
        if 'temp_s3_key' in locals():
             try:
                  s3_client.delete_object(Bucket=TEMP_UPLOAD_BUCKET, Key=temp_s3_key)
                  print(f"Cleaned up temporary file: {temp_s3_key}")
             except Exception as cleanup_e:
                  print(f"Warning: Failed to cleanup temp file {temp_s3_key} during error handling. Error: {cleanup_e}")
        # Attempt to delete potentially failed/stuck transcription job
        if 'transcribe_job_name' in locals():
             try:
                  transcribe_client.delete_transcription_job(TranscriptionJobName=transcribe_job_name)
                  print(f"Cleaned up transcription job: {transcribe_job_name}")
             except Exception as cleanup_e:
                  print(f"Warning: Failed to cleanup transcription job {transcribe_job_name} during error handling. Error: {cleanup_e}")

        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'OPTIONS,POST'
            },
            'body': json.dumps({'error': f"An error occurred: {str(e)}"})
        }