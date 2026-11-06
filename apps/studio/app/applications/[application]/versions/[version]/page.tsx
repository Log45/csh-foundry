import { PublishedApplication } from "@/features/application-runtime";
export default async function Page({
  params,
}: {
  params: Promise<{ application: string; version: string }>;
}) {
  const { application, version } = await params;
  return (
    <main>
      <a href="/">Back to workspace</a>
      <PublishedApplication application={application} version={version} />
    </main>
  );
}
