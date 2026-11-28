import { Redirect } from "expo-router";
import { useAuth } from "@/lib/auth";

/** A cold start can land on "/" before the sign-in state is known (or on a link the person
 *  may not open yet). Send them to the right front door instead of an error page. */
export default function NotFound() {
  const { status } = useAuth();
  if (status === "loading") return null;
  return <Redirect href={status === "signedIn" ? "/" : "/signin"} />;
}
