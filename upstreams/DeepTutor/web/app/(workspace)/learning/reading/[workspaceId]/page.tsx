import { MnemosyneReader } from "@/features/mnemosyne/screens";

export default async function NewImmersiveReadingSessionRoute({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <MnemosyneReader documentID={workspaceId} />;
}
