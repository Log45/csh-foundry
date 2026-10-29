"use client";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main>
      <h1>Workspace unavailable</h1>
      <p>Retry the request or sign in again.</p>
      <button onClick={reset}>Try again</button>
    </main>
  );
}
