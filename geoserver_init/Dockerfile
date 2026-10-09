FROM curlimages/curl:8.11.0

COPY --chown=curl_user:curl_user setup.sh /setup.sh

ENTRYPOINT ["/bin/sh", "/setup.sh"]
