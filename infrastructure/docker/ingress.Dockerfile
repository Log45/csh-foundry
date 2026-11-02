# Supplier's maintained stable release fixes the remaining nginx-core advisories.
FROM nginx:1.30.6-alpine@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949
# The profile needs built-in HTTP proxy/TLS only; drop unused vendor modules/libraries.
RUN apk del nginx-module-acme nginx-module-geoip nginx-module-image-filter nginx-module-njs nginx-module-xslt \
    && apk upgrade --no-cache
