# AvatarTalk LiveKit Agents Integration

This directory contains examples for integrating AvatarTalk with LiveKit Agents to create AI-powered avatar conversations in real-time.

## What is AvatarTalk Integration?

AvatarTalk integration enables LiveKit Agents to use animated avatars during conversations. The integration provides:

- Real-time avatar animation synchronized with speech
- Customizable avatar emotions and expressions
- Seamless integration with OpenAI's language models
- LiveKit room-based communication

## Setup Requirements

Before running the examples, you'll need:

### API Keys
- **AvatarTalk API Key**: Get from [AvatarTalk.ai](https://avatartalk.ai)
- **OpenAI API Key**: For language model interactions
- **LiveKit Credentials**: API key, secret, and URL

### Environment Variables
```bash
export AVATARTALK_API_KEY="your_avatartalk_api_key"
export AVATARTALK_API_URL="https://api.avatartalk.ai"
export AVATARTALK_AVATAR="your_avatar_id"  # e.g., "african_man"
export AVATARTALK_EMOTION="neutral"        # or "happy", etc.
export OPENAI_API_KEY="your_openai_api_key"
export LIVEKIT_API_KEY="your_livekit_api_key"
export LIVEKIT_API_SECRET="your_livekit_api_secret"
export LIVEKIT_URL="your_livekit_url"
```

## How to Run

1. Clone the LiveKit Agents repository:
   ```bash
   git clone https://github.com/livekit/agents.git
   cd agents
   ```

2. Set up your environment variables (see above)

3. Navigate to the AvatarTalk example:
   ```bash
   cd examples/avatar_agents/avatartalk/
   ```

4. Install dependencies and run:
   ```bash
   pip install -r requirements.txt
   python agent_worker.py dev
   ```

