import type { Metadata } from "next";
import { connection } from "next/server";
import "./style.css";
export const metadata: Metadata = {
  title: "Foundry · Ontology workspace",
  description:
    "Native ontology authoring and governed operational data exploration",
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
