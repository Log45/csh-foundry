import type { Metadata } from "next";
import "./style.css";
export const metadata: Metadata = {
  title: "Foundry · Ontology workspace",
  description:
    "Native ontology authoring and governed operational data exploration",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
