# Chromium 59, headless, for bin/test-legacy-browser.sh: the browser of an Android 4.4 tablet,
# the oldest the dashboard's legacy build is for. It listens for the DevTools protocol on 9222.
#
# A snapshot build from the 59 branch point, which Chromium's archive keeps for Linux x64 only;
# on another machine Docker runs it emulated.
FROM --platform=linux/amd64 debian:bookworm-slim

ARG CHROMIUM_POSITION=464625
ARG CHROMIUM_SHA256=3cc69a6b4aef3aa73fd9bcfd92c3b0deeb682d50521a5a7d189afe334caedb67

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl unzip fonts-dejavu-core \
      libasound2 libatk1.0-0 libcups2 libdbus-1-3 libexpat1 libfontconfig1 libgconf-2-4 libglib2.0-0 \
      libgtk-3-0 libnss3 libpango-1.0-0 libx11-6 libx11-xcb1 libxcomposite1 libxcursor1 \
      libxdamage1 libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 libxss1 libxtst6 \
    && curl -fsSL -o /tmp/chrome.zip \
      "https://commondatastorage.googleapis.com/chromium-browser-snapshots/Linux_x64/${CHROMIUM_POSITION}/chrome-linux.zip" \
    && echo "${CHROMIUM_SHA256}  /tmp/chrome.zip" | sha256sum -c - \
    && unzip -q /tmp/chrome.zip -d /opt && rm /tmp/chrome.zip \
    && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

EXPOSE 9222

ENTRYPOINT ["/opt/chrome-linux/chrome", "--headless", "--disable-gpu", "--no-sandbox", \
  "--window-size=960,600", "--remote-debugging-address=0.0.0.0", "--remote-debugging-port=9222"]
CMD ["about:blank"]
