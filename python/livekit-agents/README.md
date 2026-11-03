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

1. Clone the LiveKit Agents repository at `livekit-agents@1.6.5`, the last release with the example:
   ```bash
   git clone --branch livekit-agents@1.6.5 https://github.com/livekit/agents.git
   cd agents
   ```

2. Set up your environment variables (see above)

3. Navigate to the AvatarTalk example:
   ```bash
   cd examples/avatar_agents/avatartalk/
   ```

4. Install dependencies and run:
   ```bash
   pip install "livekit-agents[openai]==1.6.5" "livekit-plugins-avatartalk==1.6.5" python-dotenv
   python agent_worker.py dev
   ```

   Set `LIVEKIT_AGENT_NAME` to register under an agent name (explicit dispatch) instead of joining every room.

The `Dockerfile` here runs the same script in a container.

