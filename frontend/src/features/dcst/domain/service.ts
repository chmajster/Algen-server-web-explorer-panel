import type { DcstService, DcstServiceInput } from "../api/types";

export type ServiceFilters = {
  search: string;
  direction: string;
  action: string;
  state: string;
};

export type ServiceValidationErrors = Partial<Record<"name" | "source" | "destination" | "direction" | "action", string>>;

export const emptyServiceDraft: DcstServiceInput = {
  name: "",
  description: "",
  direction: "OUT",
  action: "ACCEPT",
  source_type: "tag",
  source_value: "",
  destination_type: "tag",
  destination_value: "",
  port_ids: [],
  enabled: true,
  logging: false,
  comment: "",
};

export const emptyServiceFilters: ServiceFilters = { search: "", direction: "", action: "", state: "" };

export function validateServiceDraft(draft: DcstServiceInput): ServiceValidationErrors {
  const errors: ServiceValidationErrors = {};
  if (!draft.name.trim()) errors.name = "Service name is required.";
  if (draft.source_type !== "any" && !draft.source_value.trim()) errors.source = "Source object is required.";
  if (draft.destination_type !== "any" && !draft.destination_value.trim()) errors.destination = "Destination object is required.";
  if (!draft.direction) errors.direction = "Direction is required.";
  if (!draft.action) errors.action = "Action is required.";
  return errors;
}

export function filterServices(services: readonly DcstService[], filters: ServiceFilters): DcstService[] {
  const search = filters.search.trim().toLowerCase();
  return services.filter((item) => {
    const text = `${item.name} ${item.description} ${item.source_value} ${item.destination_value} ${item.direction} ${item.action}`.toLowerCase();
    return (!search || text.includes(search))
      && (!filters.direction || item.direction === filters.direction)
      && (!filters.action || (item.blocked ? "DROP" : item.action) === filters.action)
      && (!filters.state || item.state === filters.state);
  });
}
