FROM odoo:19.0@sha256:27f920e002c43a1af7022a68f3cc17db71a2f9f3348800cb050721ce54893e49
USER root
RUN python3 -c "import urllib.request; urllib.request.urlretrieve('https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb', '/tmp/chrome.deb')" \
    && apt-get update && apt-get install -y --no-install-recommends /tmp/chrome.deb \
    && rm -f /tmp/chrome.deb && rm -rf /var/lib/apt/lists/*
ENV CHROME_BIN=/usr/bin/google-chrome
USER odoo

USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3-websocket && rm -rf /var/lib/apt/lists/*
USER odoo
