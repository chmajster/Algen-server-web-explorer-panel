export type {
  DcstIPSet,
  DcstOverview,
  DcstPort,
  DcstService,
  DcstServiceInput,
  DcstTag,
} from "../../../modules/dcst/api/client";

// API DTOs live behind this feature boundary. Domain/form state must not be
// added to this module; generated OpenAPI types can replace these aliases
// incrementally without leaking transport models into view components.
