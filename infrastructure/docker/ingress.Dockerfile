# Maintained unprivileged supplier image; digest verified with buildx imagetools inspect.
FROM nginxinc/nginx-unprivileged:1.30.6-alpine@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03
# Render into scoped ephemeral storage, not /etc, under any nonzero UID/GID.
USER root
# These supplier modules and curl are unused by this HTTP/TLS proxy profile.
RUN apk del curl nginx-module-geoip nginx-module-image-filter nginx-module-njs nginx-module-xslt \
    && apk upgrade --no-cache
RUN sed -i 's@include /etc/nginx/conf.d/\*.conf;@include /tmp/conf.d/*.conf;@' /etc/nginx/nginx.conf
ENV NGINX_ENVSUBST_OUTPUT_DIR=/tmp/conf.d
USER 101:101
ENTRYPOINT ["/bin/sh", "-ec"]
CMD ["mkdir -p /tmp/conf.d; envsubst '$STUDIO_HOST $API_HOST $IDENTITY_HOST' < /etc/nginx/templates/default.conf.template > /tmp/conf.d/default.conf; exec nginx -g 'daemon off;' -c /etc/nginx/nginx.conf"]
