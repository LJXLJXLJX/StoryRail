import type { Location, LocationImage } from "./types";

export type LocationFields = Partial<
  Pick<Location, "name" | "description" | "key_light">
>;
export type LocationImageFields = Partial<
  Pick<
    LocationImage,
    "name" | "kind" | "description" | "prompt_text" | "reference_asset_ids" | "source"
  >
>;
export type LocationOperation =
  | {
      op: "create_location";
      key: string;
      name: string;
      description: string;
    }
  | { op: "update_location"; location_id: string; fields: LocationFields }
  | { op: "delete_location"; location_id: string }
  | { op: "create_image"; location_id: string; key: string; fields: LocationImageFields }
  | { op: "update_image"; image_id: string; fields: LocationImageFields }
  | { op: "delete_image" | "clear_image_selection"; image_id: string }
  | {
      op: "upsert_fixture";
      location_id: string;
      fixture: string;
      name: string;
      description: string;
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
  ;
export interface LocationPatch {
  scope: { location_ids: string[]; scene_ids: string[] };
  operations: LocationOperation[];
}
export type LocationChange =
  | { name: "location.apply_operations"; arguments: LocationPatch }
  | {
      name: "location.select_image";
      arguments: { image_id: string; asset_id: string };
    };
export interface SoftReferenceClear {
  shot_id: string;
  scene_id: string;
  label: string;
}
export interface LocationImpact {
  revision: number;
  command_name: string;
  will_write: boolean;
  high_impact: boolean;
  changed_ids: string[];
  invalidated: string[];
  preserved: string[];
  soft_reference_clears: SoftReferenceClear[];
}
