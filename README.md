# Scheduled Message Processor

A scheduled Python application for processing selected Telegram messages.

## Configuration

The application uses GitHub Actions Secrets for all
credentials and runtime configuration.

Required secrets:

- API_ID
- API_HASH
- SESSION
- TARGET_CHAT
- SOURCE_A
- SOURCE_B
- SOURCE_C
- SOURCE_D
- TOPIC_A
- TOPIC_B

No credentials, chat names, or message content are stored
in the source code.

Runtime state is stored separately from the source code.
