import { Suspense } from "react";
import { EventEditor } from "@/components/admin/EventEditor";

async function Editor({ params }: Pick<PageProps<"/admin/events/[id]">, "params">) {
  const { id } = await params;
  return <EventEditor eventId={id} />;
}

export default function Page(props: PageProps<"/admin/events/[id]">) {
  return <Suspense fallback={<div className="skeleton" style={{ height: 48, maxWidth: 360 }} />}><Editor params={props.params} /></Suspense>;
}
