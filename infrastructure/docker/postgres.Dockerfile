# Preserve PostgreSQL 17, Debian/glibc, extensions, locales and physical-backup layout.
FROM postgres:17.11-trixie@sha256:3b0cda93be7c8dba2ed484d19393d93845dc3dafb88973e248ba8e6d99d784e1
# GnuPG verifies build-time downloads in the supplier build; serving/restore uses no GPG.
# Keep apt/sqv, gosu, Perl, libxml2 and all PostgreSQL shared-library dependencies.
RUN apt-get purge -y --auto-remove gnupg gnupg-l10n gpg gpg-agent gpgconf gpgsm dirmngr mount \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
