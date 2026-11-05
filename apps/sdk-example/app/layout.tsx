import type { ReactNode } from "react";
export default function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body
        style={{
          fontFamily: "system-ui",
          maxWidth: 1000,
          margin: "2rem auto",
          padding: 20,
        }}
      >
        {children}
      </body>
    </html>
  );
}
