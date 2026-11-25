"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api-client";
import type { JobsOverview } from "@/lib/types";

/** On every admin page: shouts if the background worker has stopped, murmurs if jobs have failed. */
export function JobsBanner() {
  const path = usePathname();
  const [o, setO] = useState<JobsOverview | null>(null);

  useEffect(() => {
    let live = true;
    const load = () => { if (!document.hidden) api<JobsOverview>("admin/jobs/overview").then((d) => live && setO(d)).catch(() => {}); };
    load();
    const id = setInterval(load, 30000);
    return () => { live = false; clearInterval(id); };
  }, []);

  if (!o) return null;
  const down = o.worker_ever_seen && !o.worker_alive;
  const failed = o.queue.failed;
  if (!down && failed === 0) return null;
  const onJobs = path.startsWith("/admin/jobs");
  return (
    <div className={`jb ${down ? "bad" : "warn"}`} role={down ? "alert" : "status"}>
      <span>
        {down
          ? <><b>The background worker is not running.</b> Tickets are not being issued or emailed, and refunds are paused, until it is started again.</>
          : <><b>{failed} background job{failed === 1 ? "" : "s"} failed.</b> Someone may be missing an email or a refund.</>}
      </span>
      {!onJobs && <Link href="/admin/jobs">Look into it</Link>}
    </div>
  );
}
