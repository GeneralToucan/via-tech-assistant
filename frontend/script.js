// --- Configuration ---
// PASTE YOUR ACTUAL API GATEWAY INVOKE URL HERE!
const API_ENDPOINT = 'https://vwvy8jxjr2.execute-api.ap-southeast-2.amazonaws.com/v1/ask'; // IMPORTANT!

// --- DOM Elements ---
const micButton = document.getElementById('micButton');
const micText = document.getElementById('micText');
const statusMessage = document.getElementById('statusMessage');
const responseArea = document.getElementById('responseArea');
const transcriptOutput = document.getElementById('transcriptOutput');
const audioPlayer = document.getElementById('audioPlayer');

// --- State Variables ---
let isRecording = false;
let mediaRecorder;
let audioChunks = [];

// --- Check for Browser Support ---
if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    updateStatus('Media Devices API not supported by your browser.', true);
    micButton.disabled = true;
}

// --- Event Listener ---
micButton.addEventListener('click', () => {
    if (!isRecording) {
        startRecording();
    } else {
        stopRecording();
    }
});

// --- Core Functions ---

async function startRecording() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        updateStatus('Media Devices API not supported.', true);
        return;
    }
    updateStatus('Requesting microphone access...');
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        isRecording = true;
        micButton.classList.add('recording');
        micText.textContent = 'Recording... Click to stop';
        updateStatus('Recording started...');
        responseArea.style.display = 'none'; // Hide previous response
        transcriptOutput.textContent = '';
        audioPlayer.src = '';
        audioPlayer.style.display = 'none';


        audioChunks = []; // Reset chunks
        // Choose a MIME type that both browser and AWS Transcribe support
        // Common options: 'audio/webm;codecs=opus', 'audio/wav', 'audio/ogg;codecs=opus'
        // Let's try webm/opus first, it's widely supported and efficient.
        // If Transcribe has issues, you might need to try 'audio/wav'.
        const options = { mimeType: 'audio/webm;codecs=opus' };
        try {
             mediaRecorder = new MediaRecorder(stream, options);
        } catch (err) {
             console.warn("Webm/Opus mimeType failed, trying default:", err);
             // Fallback to browser default if specific mimeType fails
             mediaRecorder = new MediaRecorder(stream);
        }

        mediaRecorder.ondataavailable = event => {
            if (event.data.size > 0) {
                audioChunks.push(event.data);
                console.log("Received audio chunk size:", event.data.size);
            }
        };

        mediaRecorder.onstop = async () => {
            console.log("Recording stopped. Total chunks:", audioChunks.length);
            if (audioChunks.length === 0) {
                console.warn("No audio chunks recorded.");
                updateStatus("No audio was recorded. Please try again.", true);
                resetMicButton();
                return;
            }

            // Combine chunks into a single Blob
            // Use the mimeType the recorder actually ended up using
            const audioBlob = new Blob(audioChunks, { type: mediaRecorder.mimeType || 'audio/webm' });
            console.log("Created Blob type:", audioBlob.type, "size:", audioBlob.size);

            // Reset recorder and stream tracks
            stream.getTracks().forEach(track => track.stop()); // Stop the mic access indicator
            mediaRecorder = null;

            // Convert Blob to Base64
            updateStatus('Processing audio...');
            try {
                 const base64Audio = await blobToBase64(audioBlob);
                 // console.log("Base64 Audio String (first 100 chars):", base64Audio.substring(0, 100));
                 sendAudioToApi(base64Audio);
            } catch (error) {
                 console.error("Error converting Blob to Base64:", error);
                 updateStatus('Error processing audio.', true);
                 resetMicButton();
            }
        };

        mediaRecorder.onerror = (event) => {
            console.error("MediaRecorder error:", event.error);
            updateStatus(`Recording error: ${event.error.name}`, true);
            isRecording = false; // Ensure state is reset on error
            resetMicButton();
            // Stop tracks if they weren't stopped already
            if (stream && stream.active) {
                 stream.getTracks().forEach(track => track.stop());
            }
            mediaRecorder = null;
        };


        mediaRecorder.start(); // Start recording

    } catch (err) {
        console.error("Error accessing microphone:", err);
        updateStatus(`Could not access microphone: ${err.message}. Please grant permission.`, true);
        resetMicButton();
    }
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop(); // This triggers the 'onstop' event handler
        // UI updates happen in onstop or if there's an immediate error
        updateStatus('Stopping recording...');
        isRecording = false; // Set state immediately
        micButton.classList.remove('recording');
        micText.textContent = 'Processing...'; // Indicate processing starts after stop
    } else {
        console.warn("Stop called but recorder not active or doesn't exist.");
        resetMicButton(); // Reset UI just in case state is inconsistent
    }
}

async function sendAudioToApi(base64AudioString) {
    // Remove the data URI prefix if it exists (e.g., "data:audio/webm;base64,")
    const base64Data = base64AudioString.split(',')[1] || base64AudioString;

    updateStatus('Sending audio to Via...');
    console.log("Sending data to API:", API_ENDPOINT);

    try {
        const response = await fetch(API_ENDPOINT, {
            method: 'POST',
            // Sending raw base64 string in the body, as expected by the Python Lambda sample
            // which decodes event['body'] directly.
            // If Lambda expected JSON like {'audioData': '...'}, change body to:
            // body: JSON.stringify({ audioData: base64Data }),
            // headers: { 'Content-Type': 'application/json' }
             body: base64Data,
             headers: {
                 // Let the browser set Content-Type for raw data, or set explicitly if needed
                 // 'Content-Type': 'application/octet-stream' // Or specific type if required
             }
        });

        if (!response.ok) {
            // Attempt to read error details from the response body
            let errorMsg = `Error: ${response.status} ${response.statusText}`;
            try {
                const errorData = await response.json();
                errorMsg = errorData.error || errorData.message || errorMsg; // Use specific error if available
            } catch (e) {
                // Ignore if response body is not JSON or empty
                 console.warn("Could not parse error response body:", e);
            }
             throw new Error(errorMsg);
        }

        const data = await response.json();
        console.log("API Response:", data);
        displayResponse(data);
        updateStatus('Response received.');

    } catch (error) {
        console.error('Error sending audio to API:', error);
        updateStatus(`Failed to get response: ${error.message}`, true);
    } finally {
        // Reset button regardless of success or failure after processing
        resetMicButton();
    }
}

function displayResponse(data) {
    if (data.transcript && data.audioUrl) {
        transcriptOutput.textContent = data.transcript;
        audioPlayer.src = data.audioUrl;
        audioPlayer.style.display = 'block'; // Show audio player
        // audioPlayer.play(); // Autoplay might be blocked by browsers, let user click play
        responseArea.style.display = 'block'; // Show the response area
        updateStatus('Response loaded. Press play to listen.'); // Update status
    } else {
        console.error("Invalid response data structure:", data);
        updateStatus('Received an invalid response from the assistant.', true);
         responseArea.style.display = 'none';
    }
}

// --- Helper Functions ---

function updateStatus(message, isError = false) {
    statusMessage.textContent = message;
    statusMessage.className = isError ? 'status-message error' : 'status-message';
    console.log(`Status Update: ${message} ${isError ? '(Error)' : ''}`);
}

function resetMicButton() {
    isRecording = false;
    micButton.classList.remove('recording');
    micText.textContent = 'Click me to ask your technological questions';
    // Keep status message as is unless explicitly cleared or updated elsewhere
}

// Converts a Blob object to a Base64 encoded string
function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = (event) => {
             console.error("FileReader error:", event.target.error);
             reject(new Error("Error reading Blob: " + event.target.error));
        };
        reader.onload = () => {
            resolve(reader.result); // result contains the Base64 encoded string with data URI prefix
        };
        reader.readAsDataURL(blob);
    });
}

// --- Initial State ---
updateStatus("Click the microphone button to start.");