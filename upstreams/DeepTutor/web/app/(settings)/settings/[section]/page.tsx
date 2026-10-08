import { redirect } from "next/navigation";

export default async function SettingsSectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  await params;
  redirect("/settings");
}
