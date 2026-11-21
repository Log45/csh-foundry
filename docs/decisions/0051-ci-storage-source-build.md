# 0051 — Rebuild the pinned test storage from upstream source

The first hosted CI run could not pull the pinned `minio/minio` and `minio/mc` images.
Fresh anonymous checks also rejected Quay pulls, and upstream release binary archive URLs
returned HTTP 410. Local cached images had hidden this failure.

Retain the same server release (`RELEASE.2025-09-07T16-13-09Z`) and client release
(`RELEASE.2025-08-13T08-35-41Z`), built from exact upstream commit archives with committed
SHA-256 checksums. Use digest-pinned Go 1.24.6 and Alpine bases, upstream go.sum dependency
verification, and readonly module files. Include the corresponding source archives in the
runtime image. Both binaries share one local image; the existing Compose service entrypoints,
credentials, isolated volumes and policy initialization remain intact. BusyBox wget supplies
the readiness check in the Alpine runtime.

Build the amd64 image once per workflow, cache the complete export by Dockerfile content,
and distribute a checksummed artifact to the regression and acceptance jobs. A missing or
failed build remains a required-gate failure. No job substitutes mocked S3 or skips storage
checks. Local validation builds the same image directly. No remote image publishing or
production deployment is introduced.

The first cache miss costs additional compile time; warm runs restore the image. This
preserves the existing storage behavior while removing reliance on unavailable prebuilt
assets. Changing storage engines or upgrading the archived releases is separate work.
