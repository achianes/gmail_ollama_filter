# Gmail Ollama Email Filter

## Project Description

This command-line tool uses Python, the Gmail API, and a local Ollama LLM instance to automatically filter emails from your Gmail inbox into designated folders. It learns from example emails you place in special `AI_AUTO_` prefixed folders in your Gmail account.

## Features

*   Connects to Gmail using OAuth2.
*   Scans specified `AI_AUTO_` folders for example emails.
*   Uses a local LLM (via Ollama) to compare new inbox emails against these examples.
*   Moves emails deemed similar to the corresponding `AI_AUTO_` folder.
*   Configuration is managed via a `config.json` file.
*   Excludes already processed emails (those labeled with an `AI_AUTO_` prefix) from subsequent scans of the inbox.

## Prerequisites

1.  **Python 3.7+**
2.  **Ollama Installed and Running:**
    *   Download and install from [ollama.com](https://ollama.com/).
    *   Ensure the Ollama service is running (e.g., `ollama serve`).
    *   Pull a model that you will use (e.g., `ollama pull qwen:14b`). Make sure this model name matches the `ollama_model` in your `config.json`.
3.  **Google Cloud Project & Gmail API Enabled:**
    *   Create a project in [Google Cloud Console](https://console.cloud.google.com/).
    *   Enable the "Gmail API" for your project.
    *   Create OAuth 2.0 Client IDs for a "Desktop app".
    *   Download the credentials JSON file and save it as `credentials.json` in the root of this project.
4.  **Gmail Setup:**
    *   In your Gmail account, create one or more labels (folders) that start with the prefix `AI_AUTO_` (e.g., `AI_AUTO_Newsletter`, `AI_AUTO_SupportTickets`).
    *   Place at least one representative example email into each of these `AI_AUTO_` folders. The script will use these as a basis for classification.

## Setup and Installation

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/TUO_USERNAME/NOME_TUO_REPOSITORY.git
    cd NOME_TUO_REPOSITORY
    ```

2.  **Create and Activate a Virtual Environment (Recommended):**
    ```bash
    python -m venv venv
    # On Windows
    # venv\Scripts\activate
    # On macOS/Linux
    # source venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Place `credentials.json`:**
    *   Ensure the `credentials.json` file (downloaded from Google Cloud Console) is in the root directory of the project.

5.  **Configure `config.json`:**
    *   Copy `config.example.json` to `config.json` (or create `config.json` from scratch).
        ```bash
        cp config.example.json config.json
        ```
    *   Edit `config.json` with your desired settings:
        *   `ollama_model`: The name of the Ollama model you want to use (e.g., `"qwen:14b"`).
        *   `ollama_host`: The host where Ollama is running (default: `"http://localhost:11434"`).
        *   `ai_folder_prefix`: The prefix for your special Gmail folders (default: `"AI_AUTO_"`).
        *   `similarity_prompt_v3`: (Advanced) The prompt template used for Ollama.
        *   `max_emails_to_scan_inbox`: Max emails to fetch from inbox per run.
        *   `max_examples_per_folder`: Max example emails to load from each `AI_AUTO_` folder (influences prompt length if all are used in the prompt).
        *   `inbox_label_name`: The name of your main inbox label in Gmail (usually `"INBOX"`).
        *   `max_body_length_for_llm`: Max characters of email body to send to LLM (to manage prompt size).
        *   `log_level`: Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). `DEBUG` is useful for development.
        *   *(Add any other relevant config options you have)*

## Running the Script

1.  **First-Time Authorization:**
    *   The first time you run the script, it will open a web browser to ask for permission to access your Gmail account.
    *   Follow the on-screen instructions to authorize the application.
    *   If your Google Cloud app is in "Testing" mode, ensure the Google account you're authorizing with has been added as a "Test user" in the OAuth consent screen settings in Google Cloud Console.
    *   A `token.json` file will be created in the root directory to store your access tokens for future runs.

2.  **Execute the Script:**
    ```bash
    python main.py
    ```

    The script will:
    *   Authenticate with Gmail.
    *   Fetch example emails from your `AI_AUTO_` folders.
    *   Fetch new emails from your inbox (excluding those already in `AI_AUTO_` folders).
    *   For each new email, query Ollama to see if it matches any `AI_AUTO_` category based on the examples.
    *   Move matching emails to the appropriate folder.
    *   Log its actions to the console.

## How it Works (Briefly)

*   The script authenticates with Gmail using OAuth2 and the `credentials.json` file.
*   It identifies all labels in Gmail starting with the `AI_AUTO_` prefix (defined in `config.json`).
*   For each `AI_AUTO_` folder, it fetches a few example emails.
*   It then fetches recent emails from the main inbox, excluding emails that already have an `AI_AUTO_` label.
*   Each new inbox email is compared against the examples from each `AI_AUTO_` category using a prompt sent to a local Ollama LLM instance.
*   The LLM is asked to determine similarity based on sender, subject, and content (as guided by the prompt in `config.json`).
*   If the LLM responds affirmatively for a category, the email is moved from the inbox to the corresponding `AI_AUTO_` folder.

## Troubleshooting

*   **`credentials.json not found`**: Ensure you've downloaded it from Google Cloud Console and placed it in the project root.
*   **`Error 403: access_denied` (during authorization)**: If your app is in "testing" mode in Google Cloud, add your Google account email as a "Test User" in the OAuth Consent Screen settings.
*   **`Error 403: accessNotConfigured` or "Gmail API has not been used..."**: Ensure the Gmail API is enabled in your Google Cloud project.
*   **Ollama Connection Issues**: Make sure Ollama is running (`ollama serve`) and accessible at the host specified in `config.json`. Check if the model specified in `config.json` is downloaded (`ollama list`).
*   **Incorrect Classifications**:
    *   Review the `DEBUG` logs to see the prompts sent to Ollama and its raw responses.
    *   Adjust the `similarity_prompt_v3` in `config.json` to be more specific or to guide the LLM better.
    *   Ensure your example emails in the `AI_AUTO_` folders are truly representative.
    *   Try a different `ollama_model` in `config.json`. Some models are better at following instructions.
    *   Adjust `max_body_length_for_llm` or `max_examples_per_folder` if prompts are too long or too noisy.

## Contributing 

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

Please make sure to update tests as appropriate. (If you have tests)

## License 

[MIT](https://choosealicense.com/licenses/mit/)


[![Support me on PayPal](https://www.paypalobjects.com/en_US/i/btn/btn_donate_LG.gif)](https://www.paypal.com/donate/?hosted_button_id=T4SKREGYTG5ES)
   
