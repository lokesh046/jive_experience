// Mirrors the backend schemas the frontend actually reads.
export type EventStatus = "DRAFT" | "PUBLISHED" | "CANCELLED" | "COMPLETED";

export interface EventListItem {
  id: string;
  slug: string;
  title: string;
  subtitle: string | null;
  category: string;
  status: EventStatus;
  starts_at: string;
  timezone: string;
  venue_name: string;
  city: string;
  thumbnail_image_url: string | null;
  banner_image_url: string | null;
  starting_price_paise: number | null;
  is_featured: boolean;
  is_sold_out: boolean;
}

export interface Venue {
  id: string;
  name: string;
  city: string;
  state: string | null;
  address_line1?: string | null;
  address_line2?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  postal_code: string | null;
  directions: string | null;
  map_url: string | null;
  description?: string | null;
  image_urls?: string[];
  benefits?: string[];
}

export interface TicketCategoryPublic {
  id: string;
  name: string;
  description: string | null;
  price_paise: number;
  currency: string;
  available: number;
  min_per_booking: number;
  max_per_booking: number;
  is_sold_out: boolean;
}

export interface Performer {
  name: string;
  role: string | null;
  photo_url: string | null;
  performs_at: string | null;
}

export interface EventDetail {
  id: string;
  slug: string;
  title: string;
  subtitle: string | null;
  description: string | null;
  category: string;
  status: EventStatus;
  starts_at: string;
  ends_at: string | null;
  timezone: string;
  sale_starts_at: string | null;
  sale_ends_at: string | null;
  on_sale: boolean;
  is_past: boolean;
  venue: Venue;
  banner_image_url: string | null;
  thumbnail_image_url: string | null;
  gallery_image_urls: string[];
  ticket_categories: TicketCategoryPublic[];
  lineup: Performer[];
  max_tickets_per_customer: number;
  requires_attendee_name: boolean;
  cancellation_policy: { tiers: { hours_before: number; percent: number }[] } | null;
  terms_and_conditions: string | null;
  location_url: string | null;
  is_sold_out: boolean;
}

export interface Availability {
  event_id: string;
  checked_at: string;
  total_available: number;
  categories: { ticket_category_id: string; name: string; price_paise: number; available: number; is_sold_out: boolean }[];
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

export type BookingStatus = "PENDING" | "CONFIRMED" | "EXPIRED" | "CANCELLED" | "REFUNDED" | "PARTIALLY_REFUNDED";

export interface BookingItem {
  ticket_category_id: string;
  category_name: string;
  unit_price_paise: number;
  quantity: number;
  line_total_paise: number;
}

export type BookingSource = "ONLINE" | "COMPLIMENTARY" | "CASH";

export interface Booking {
  id: string;
  reference: string;
  source?: BookingSource;
  event_id: string;
  status: BookingStatus;
  quantity: number;
  subtotal_paise: number;
  fees_paise: number;
  discount_paise?: number;
  total_paise: number;
  refunded_paise: number;
  currency: string;
  expires_at: string | null;
  confirmed_at: string | null;
  cancelled_at: string | null;
  created_at: string;
  items: BookingItem[];
}

export interface CheckoutResponse {
  provider: string;
  provider_order_id: string;
  amount_paise: number;
  currency: string;
  booking_reference: string;
  checkout_payload: { key: string; order_id: string; amount: number; currency: string; name: string; receipt?: string };
}

export type TicketStatus = "ISSUED" | "CHECKED_IN" | "CANCELLED" | "REFUNDED" | string;

export interface Ticket {
  id: string;
  qr_token: string | null;
  serial: string;
  booking_id: string;
  event_id: string;
  ticket_category_id: string;
  status: TicketStatus;
  attendee_name: string | null;
  issued_at: string | null;
  checked_in_at: string | null;
}

export interface RefundQuote {
  eligible: boolean;
  amount_paise: number;
  percent: number;
  reason: string;
}

export interface UserProfile {
  id: string;
  role: string;
  email: string;
  full_name: string | null;
  phone_e164: string | null;
  avatar_url: string | null;
  created_at: string;
}

export interface AuthUser {
  id: string;
  role: "CUSTOMER" | "EVENT_STAFF" | "ADMIN";
  email: string;
  full_name: string | null;
  phone_e164: string | null;
  avatar_url: string | null;
}

export interface AssignedEvent {
  event_id: string;
  slug: string;
  title: string;
  starts_at: string;
  venue_name: string;
  city: string;
}

export type ScanResult = "SUCCESS" | "ALREADY_USED" | "WRONG_EVENT" | "CANCELLED" | "REFUNDED" | "INVALID" | "NOT_ASSIGNED" | "EXPIRED";

export interface ScanResponse {
  result: ScanResult;
  ok: boolean;
  message: string;
  ticket_serial: string | null;
  ticket_category: string | null;
  attendee_name: string | null;
  checked_in_at: string | null;
}

export interface Attendance {
  event_id: string;
  issued: number;
  checked_in: number;
  cancelled: number;
  refunded: number;
  total: number;
}

// ---- admin ----
export interface VenueFull {
  id: string;
  name: string;
  address_line1: string;
  address_line2: string | null;
  city: string;
  state: string | null;
  postal_code: string | null;
  country_code: string;
  map_url: string | null;
  directions: string | null;
  description: string | null;
  image_urls: string[];
  benefits: string[];
}

export interface CategoryAdmin {
  id: string;
  event_id: string;
  name: string;
  description: string | null;
  price_paise: number;
  currency: string;
  capacity: number;
  reserved_count: number;
  sold_count: number;
  available: number;
  min_per_booking: number;
  max_per_booking: number;
  sort_order: number;
  is_active: boolean;
}

export interface EventAdmin {
  id: string;
  slug: string;
  title: string;
  subtitle: string | null;
  description: string | null;
  category: string;
  status: string;
  venue: VenueFull;
  starts_at: string;
  ends_at: string | null;
  timezone: string;
  sale_starts_at: string | null;
  sale_ends_at: string | null;
  banner_image_url: string | null;
  thumbnail_image_url: string | null;
  gallery_image_urls: string[];
  performers: (Performer & { id: string })[];
  max_tickets_per_customer: number;
  requires_attendee_name: boolean;
  terms_and_conditions: string | null;
  cancellation_policy: { tiers: { hours_before: number; percent: number }[] } | null;
  location_url: string | null;
  is_featured: boolean;
  published_at: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  ticket_categories: CategoryAdmin[];
}

export interface BookingAdmin extends Booking {
  user_id: string;
  cancellation_reason: string | null;
  customer_note: string | null;
}

export interface RefundRow {
  id: string;
  amount_paise: number;
  status: string;
  reason: string;
  reason_note: string | null;
  failure_reason: string | null;
  created_at: string;
}

export interface UserAdmin {
  id: string;
  role: string;
  status: string;
  email: string;
  full_name: string | null;
  phone_e164: string | null;
  last_login_at: string | null;
  created_at: string;
}

export interface StaffAssignment {
  id: string;
  user_id: string;
  event_id: string;
  full_name: string | null;
  email: string | null;
}

export interface SalesTotals {
  gross_paise: number; refunded_paise: number; net_paise: number;
  tickets_sold: number; bookings: number; cancelled_bookings: number; checked_in: number; capacity: number;
}
export interface SalesEventRow extends SalesTotals { event_id: string; title: string; slug: string; starts_at: string; status: EventStatus }
export interface SalesDay { day: string; tickets: number; gross_paise: number }
export interface SalesCategoryRow { name: string; price_paise: number; capacity: number; tickets_sold: number; gross_paise: number; is_active: boolean }
export interface SalesReport {
  summary: SalesTotals; events: SalesEventRow[]; daily: SalesDay[]; categories: SalesCategoryRow[];
  days: number; timezone: string; generated_at: string;
}

export interface AttendeeRow {
  serial: string; ticket_type: string; status: "ISSUED" | "CHECKED_IN" | "CANCELLED" | "REFUNDED";
  attendee_name: string | null; customer_name: string | null; customer_email: string;
  booking_reference: string; source?: BookingSource; checked_in_at: string | null;
}
export interface ScanRow {
  scanned_at: string; result: "SUCCESS" | "ALREADY_USED" | "WRONG_EVENT" | "CANCELLED" | "REFUNDED" | "INVALID";
  serial: string | null; ticket_type: string | null; staff: string | null; device_label: string | null;
}

export interface Enquiry {
  id: string; name: string; email: string; phone: string | null; event_date: string | null; guests: number | null;
  message: string; status: "NEW" | "CONTACTED" | "CLOSED"; admin_note: string | null; created_at: string;
}
export interface EnquiryPage extends Page<Enquiry> { counts: Record<string, number> }
export interface Subscriber { email: string; subscribed: boolean; created_at: string; unsubscribed_at: string | null }
export interface SubscriberPage extends Page<Subscriber> { active: number }

export interface WaitlistRow { email: string; quantity: number; ticket_type: string | null; status: "WAITING" | "NOTIFIED" | "LEFT"; created_at: string; notified_at: string | null }
export interface WaitlistPage extends Page<WaitlistRow> { waiting: number; notified: number }

export interface PromoCheck { code: string; subtotal_paise: number; discount_paise: number; total_paise: number; description: string | null }
export interface Promo {
  id: string; code: string; description: string | null; discount_type: "PERCENT" | "FIXED";
  percent_off: number | null; amount_off_paise: number | null; event_id: string | null;
  max_uses: number | null; used_count: number; max_uses_per_customer: number | null;
  valid_from: string | null; valid_until: string | null; is_active: boolean; created_at: string;
}
