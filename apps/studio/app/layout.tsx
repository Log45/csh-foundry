import type { Metadata } from "next";
import { connection } from "next/server";
import "./style.css";
export const metadata: Metadata = {
  title: "Foundry · Ontology workspace",
  description:
    "Native ontology authoring and governed operational data exploration",
  icons: {
    icon: [
      { url: "/brand/foundry-black.png", type: "image/png" },
      {
        url: "/brand/foundry-magenta.png",
        type: "image/png",
        media: "(prefers-color-scheme: light)",
      },
      {
        url: "/brand/foundry-black.png",
        type: "image/png",
        media: "(prefers-color-scheme: dark)",
      },
    ],
  },
};
export default async function Layout({
  children,
}: {
  children: React.ReactNode;
}) {
  await connection();
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
