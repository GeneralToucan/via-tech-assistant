# Via: AI Tech Assistant for Seniors
AI tech voice assistant for Seniors.

**Demo Video Link:** https://www.youtube.com/watch?v=iKEuagyOaqU

## Inspiration
The rapid pace of technological change often leaves seniors struggling to keep up, particularly those without prior tech education. As a volunteer tech assistant supporting senior patrons in a Sydney local council library, I frequently encounter common questions about basic laptop and mobile phone usage.

To address this, I propose leveraging generative AI to develop a virtual voice assistant named Via. This AI assistant would mimic my role, providing accessible tech support to seniors and helping to bridge the digital gap, potentially through integration with the local council's app or website.

## What it does
Project Via is an accessible web-based platform designed to provide voice-activated tech assistance, primarily for senior citizens. It offers a convenient alternative to typing, allowing users to simply speak their questions.

## Operations:
- **Voice Input:** Users speak their queries into any device with web access.
- **AI Processing:** This input is transcribed and sent to an AI agent, which researches and formulates a relevant answer.
- **Dual Output:** The answer is then presented to the user in both textual and spoken formats.
- **Audio Control:** Users can read the textual answer and also listen to an AI voice read it aloud, with adjustable volume, pause, and replay options.

## How I built it
Via was built using AWS Services such as S3, Transcribe, Polly, API Gateway, Lambda, Bedrock -utilising Claude 3 Haiku-, and its frontend was designed using JavaScript, HTML and distributed with CloudFront. The avatar for Via was generated using SeaArt AI.

S3 was used to create three buckets;
- **Private audio bucket** for Via’s response
- **Temporary upload bucket** for the transcript
- **Static website bucket** for frontend

Through the Lambda function, the user’s audio would be recorded, stored in a temporary S3 bucket mentioned previously and then sent through to Transcribe which would extract what the user said before sending the transcript to Bedrock’s Claude 3 Haiku to generate the answer to the user’s question. 

The System Prompt for the model is set to ***"You are Via, a friendly, patient, and clear virtual tech voice assistant helping senior citizens. Answer the user's technology question simply and step-by-step if possible. Avoid jargon. Keep responses concise but helpful."*** such that it is customised for Via’s specific use case in helping seniors resolve tech issues.

Next, Polly is used to synthesize the LLM’s response into audio before uploading it to the audio bucket in S3, and the response is returned using API Gateway back to the user in both transcript and audio form.
