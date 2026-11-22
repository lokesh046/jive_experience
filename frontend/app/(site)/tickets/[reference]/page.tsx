import type { Metadata } from "next";
import { Suspense } from "react";
import { BookingView } from "./BookingView";

export const metadata: Metadata = { title: "Your booking", robots: { index: false, follow: false } };

async function View({ params }: Pick<PageProps<"/tickets/[reference]">, "params">) {
  const { reference } = await params;
  return <BookingView reference={reference} />;
}

export default function Page(props: PageProps<"/tickets/[reference]">) {
  return (
    <Suspense fallback={<main className="page"><div className="wrap"><div className="skeleton" style={{ height: 56, maxWidth: 420 }} /></div></main>}>
      <View params={props.params} />
    </Suspense>
  );
}
