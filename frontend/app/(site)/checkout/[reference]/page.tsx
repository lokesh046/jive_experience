import type { Metadata } from "next";
import { Suspense } from "react";
import { CheckoutFlow } from "./CheckoutFlow";

export const metadata: Metadata = { title: "Checkout", robots: { index: false, follow: false } };

async function Flow({ params }: Pick<PageProps<"/checkout/[reference]">, "params">) {
  const { reference } = await params;
  return <CheckoutFlow reference={reference} />;
}

export default function CheckoutPage(props: PageProps<"/checkout/[reference]">) {
  return (
    <Suspense fallback={<main className="page"><div className="wrap"><div className="skeleton" style={{ height: 56, maxWidth: 420 }} /></div></main>}>
      <Flow params={props.params} />
    </Suspense>
  );
}
