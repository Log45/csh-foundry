// Test harness only. Preserve issuer identity while remapping its network socket to an unprivileged port.
if (process.env.NODE_ENV === "production")
  throw Error("Test transport cannot run in production");
const original = globalThis.fetch;
globalThis.fetch = (input, init) => {
  const raw =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
  if (raw.startsWith("https://127.0.0.1/oidc/")) {
    const url = raw.replace("https://127.0.0.1/", "https://127.0.0.1:8443/");
    return original(
      input instanceof Request ? new Request(url, input) : url,
      init,
    );
  }
  return original(input, init);
};
