export async function register() {
  if (
    process.env.NEXT_RUNTIME === "nodejs" &&
    process.env.STUDIO_ENVIRONMENT === "production"
  ) {
    const { config } = await import("./lib/server");
    config();
  }
}
