export interface StitchConfig {
  sessionId: string;
  auto_stitch_threshold: number;
  auto_stitch_enabled: boolean;
  folder_monitoring_enabled: boolean;
  output_name: string;
}

export interface StitchSessionSummary {
  session_id: string;
  image_count: number;
  is_stitching: boolean;
  monitoring: boolean;
  auto_stitch: boolean;
}

export interface StitchSessionStatus {
  session_id: string;
  image_count: number;
  is_stitching: boolean;
  auto_stitch_enabled: boolean;
  auto_stitch_threshold: number;
  folder_monitoring_enabled: boolean;
  last_stitch_count: number;
  images_since_last_stitch: number;
}

export type StitchWsEvent =
  | {
      type: "file_detected";
      file: string;
      total_images: number;
    }
  | {
      type: "stitching_started";
      image_count: number;
    }
  | {
      type: "stitching_completed";
      success: boolean;
      elapsed_time: number;
      error_message: string | null;
      output_file: string | null;
    };

export type StitchEventRecord = StitchWsEvent & {
  id: number;
  receivedAt: string;
};

export interface StitchIntermediateList {
  session_id: string;
  count: number;
  files: string[];
}

export interface StitchStreamSource {
  uavId: number;
  label: string;
  streamPort: number;
  jsonPort?: number;
}
