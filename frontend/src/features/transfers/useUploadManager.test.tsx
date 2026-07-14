import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { useUploadManager } from "./useUploadManager";

vi.mock("../../api", () => ({ api: { startUpload: vi.fn(), uploadChunk: vi.fn(), cancelUpload: vi.fn() } }));

describe("upload manager", () => {
  it("pauses an active chunk and resumes from the same upload session", async () => {
    vi.mocked(api.startUpload).mockResolvedValue({ upload_id: "session-1", offset: 0, size: 2 * 1024 * 1024, path: "/home/a.bin", completed: false });
    let first = true;
    vi.mocked(api.uploadChunk).mockImplementation(async (_id, offset, chunk, signal) => {
      if (first) {
        first = false;
        return await new Promise((_, reject) => signal?.addEventListener("abort", () => reject(new Error("aborted"))));
      }
      return { upload_id: "session-1", offset: offset + chunk.size, size: 2 * 1024 * 1024, path: "/home/a.bin", completed: offset + chunk.size === 2 * 1024 * 1024 };
    });
    const { result } = renderHook(() => useUploadManager());
    let ids: string[] = [];
    act(() => { ids = result.current.controls.add([new File([new Uint8Array(2 * 1024 * 1024)], "a.bin")], "/home"); });
    expect(ids).toHaveLength(1);
    await waitFor(() => expect(api.uploadChunk).toHaveBeenCalledOnce());
    const id = result.current.tasks[0].id;
    act(() => result.current.controls.pause(id));
    await waitFor(() => expect(result.current.tasks[0].status).toBe("paused"));
    act(() => result.current.controls.resume(id));
    await waitFor(() => expect(result.current.tasks[0].status).toBe("completed"));
    expect(api.startUpload).toHaveBeenCalledOnce();
    expect(api.uploadChunk).toHaveBeenCalledTimes(3);
  });
});
