# livekit/agents' AvatarTalk example (examples/avatar_agents/avatartalk), run as-is. Upstream removed it after
# livekit-agents 1.6.5, so the packages and the script are pinned to that release.
FROM python:3.12-slim

ARG LIVEKIT_AGENTS_VERSION=1.6.5
ARG LIVEKIT_AGENTS_COMMIT=dbc38dfbc113a2e06d36feb1278e543af3585ea9
# The release current with livekit-agents 1.6.5: openai 3 swapped httpx (imported by livekit-agents) for httpx2.
ARG OPENAI_VERSION=2.45.0

# The example registers without an agent name; the playground and act-it-out's LiveKit agent healthcheck
# dispatch `avatartalk-agent` explicitly.
ENV PYTHONUNBUFFERED=1 \
    LIVEKIT_AGENT_NAME=avatartalk-agent

RUN pip install --no-cache-dir \
    "livekit-agents[openai]==${LIVEKIT_AGENTS_VERSION}" \
    "livekit-plugins-avatartalk==${LIVEKIT_AGENTS_VERSION}" \
    "openai[realtime]==${OPENAI_VERSION}" \
    python-dotenv

WORKDIR /app
ADD https://raw.githubusercontent.com/livekit/agents/${LIVEKIT_AGENTS_COMMIT}/examples/avatar_agents/avatartalk/agent_worker.py ./

CMD ["python", "agent_worker.py", "start"]
