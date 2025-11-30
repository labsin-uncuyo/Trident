# Install OpenCode
RUN curl -fsSL https://opencode.ai/install | bash

# Add OpenCode to PATH
ENV PATH="/root/.opencode/bin:${PATH}"

# Create config directories
RUN mkdir -p /root/.config/opencode \
    && mkdir -p /root/.local/share/opencode

# Copy OpenCode configuration template (if file exists in build context)
COPY opencode.json /root/.config/opencode/opencode.json.template 2>/dev/null || true