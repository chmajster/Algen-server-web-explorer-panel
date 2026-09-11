import { request } from "../../../core/api/transport";

export type ImageFormat = { id: string; extension: string; lossy: boolean };
export type ImageConverterLimits = {
  max_upload_files: number;
  max_directory_files: number;
  max_file_bytes: number;
  max_batch_bytes: number;
  max_pixels: number;
  max_dimension: number;
};
export type BrowserEntry = { name: string; path: string };
export type BrowserImage = BrowserEntry & { size: number };
export type DirectoryBrowser = {
  path: string;
  parent: string | null;
  directories: BrowserEntry[];
  images: BrowserImage[];
  truncated: boolean;
};
export type ConversionFailure = { source: string; code: string; message: string };
export type ConversionSummary = {
  converted_count: number;
  failed_count: number;
  skipped_count: number;
  source_bytes: number;
  output_bytes: number;
  saved_bytes: number;
};
export type ConversionResult = {
  format: string;
  converted: Array<{ source: string; output: string; size: number; source_size: number; width: number; height: number }>;
  failed: ConversionFailure[];
  skipped?: string[];
  summary?: ConversionSummary;
  output_directory?: string;
  batch_id?: string;
  download_url?: string;
};
export type ConversionOptions = {
  format: string;
  quality: number;
  width?: number;
  height?: number;
  keep_aspect: boolean;
  strip_metadata: boolean;
  prefix: string;
  suffix: string;
};

export const imageConverterClient = {
  formats: () => request<{ formats: ImageFormat[]; limits: ImageConverterLimits }>("/api/modules/image-converter/formats"),
  browse: (path?: string) => request<DirectoryBrowser>(`/api/modules/image-converter/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  convertDirectory: (payload: ConversionOptions & { source_directory: string; output_directory?: string; recursive: boolean; overwrite_policy: "rename" | "skip" | "overwrite" }) => request<ConversionResult>("/api/modules/image-converter/directory", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  convertUpload: (files: File[], options: ConversionOptions) => {
    const body = new FormData();
    files.forEach((file) => body.append("files", file, file.name));
    body.append("output_format", options.format);
    body.append("quality", String(options.quality));
    if (options.width) body.append("width", String(options.width));
    if (options.height) body.append("height", String(options.height));
    body.append("keep_aspect", String(options.keep_aspect));
    body.append("strip_metadata", String(options.strip_metadata));
    body.append("prefix", options.prefix);
    body.append("suffix", options.suffix);
    return request<ConversionResult>("/api/modules/image-converter/upload", { method: "POST", body });
  },
};
