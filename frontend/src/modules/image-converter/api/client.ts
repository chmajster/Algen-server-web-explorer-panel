import { request } from "../../../core/api/transport";

export type ImageFormat = { id: string; extension: string; lossy: boolean };
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
export type ConversionResult = {
  format: string;
  converted: Array<{ source: string; output: string; size: number }>;
  failed: ConversionFailure[];
  output_directory?: string;
  batch_id?: string;
  download_url?: string;
};

export const imageConverterClient = {
  formats: () => request<{ formats: ImageFormat[] }>("/api/modules/image-converter/formats"),
  browse: (path?: string) => request<DirectoryBrowser>(`/api/modules/image-converter/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  convertDirectory: (payload: { source_directory: string; output_directory?: string; format: string; quality: number; recursive: boolean }) => request<ConversionResult>("/api/modules/image-converter/directory", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  convertUpload: (files: File[], outputFormat: string, quality: number) => {
    const body = new FormData();
    files.forEach((file) => body.append("files", file, file.name));
    body.append("output_format", outputFormat);
    body.append("quality", String(quality));
    return request<ConversionResult>("/api/modules/image-converter/upload", { method: "POST", body });
  },
};
