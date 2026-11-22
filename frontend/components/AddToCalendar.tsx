import { googleCalendarUrl, type CalendarEvent } from "@/lib/calendar";

/** A small menu: Google Calendar in a new tab, or a .ics file that Apple Calendar and Outlook open. No script needed. */
export function AddToCalendar({ event, align = "center" }: { event: CalendarEvent; align?: "center" | "start" }) {
  return (
    <details className={`cal ${align}`}>
      <summary className="pill ghost">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15" rx="3" /><path d="M8 3v4M16 3v4M3.5 10h17" /></svg>
        Add to calendar
      </summary>
      <div className="cal-menu">
        <a href={googleCalendarUrl(event)} target="_blank" rel="noopener noreferrer">Google Calendar</a>
        <a href={`/events/${event.slug}/calendar.ics`} download>Apple, Outlook and others (.ics)</a>
      </div>
    </details>
  );
}
