import type { Location, LocationView } from "./types";

export type LocationFields = Partial<
  Pick<Location, "name" | "kind" | "description" | "key_light">
> & {
  master_prompt_text?: string;
  master_reference_asset_ids?: string[];
};
export type ViewFields = Partial<
  Pick<
    LocationView,
    | "name"
    | "purpose"
    | "azimuth_deg"
    | "look_at_fixture_id"
    | "yaw_offset_deg"
    | "pitch_deg"
    | "hfov_deg"
    | "state_id"
    | "refine_prompt_text"
    | "reference_view_ids"
  >
>;
export type LocationOperation =
  | {
      op: "create_location";
      key: string;
      name: string;
      kind: Location["kind"];
      description: string;
    }
  | { op: "update_location"; location_id: string; fields: LocationFields }
  | { op: "delete_location" | "clear_master_selection"; location_id: string }
  | { op: "create_view"; location_id: string; key: string; fields: ViewFields }
  | { op: "update_view"; view_id: string; fields: ViewFields }
  | { op: "delete_view" | "clear_view_selection"; view_id: string }
  | {
      op: "upsert_fixture";
      location_id: string;
      fixture: string;
      name: string;
      description: string;
      azimuth_deg: number | null;
    }
  | { op: "delete_fixture"; location_id: string; fixture_id: string }
  | {
      op: "upsert_state";
      location_id: string;
      state: string;
      name: string;
      description: string;
    }
  | { op: "delete_state"; location_id: string; state_id: string }
  | {
      op: "bind_scene";
      scene_id: string;
      location_id: string | null;
      state_id: string | null;
    }
  | { op: "bind_shot"; shot_id: string; view_id: string | null };
export interface LocationPatch {
  scope: { location_ids: string[]; scene_ids: string[]; shot_ids: string[] };
  operations: LocationOperation[];
}
export type LocationChange =
  | { name: "location.apply_operations"; arguments: LocationPatch }
  | {
      name: "location.select_master";
      arguments: { location_id: string; asset_id: string };
    }
  | {
      name: "location.select_view";
      arguments: { view_id: string; asset_id: string };
    };
export interface LocationImpact {
  revision: number;
  command_name: string;
  will_write: boolean;
  high_impact: boolean;
  changed_ids: string[];
  invalidated: string[];
  preserved: string[];
}
