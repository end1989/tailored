import { deleteDocument, deleteProfile, getSettings, updateSettings } from "./api";

const SETTINGS = {
  api_key_set: false,
  fake_mode: true,
  default_template: "slate",
  default_depth: "standard",
  page_size: "Letter",
};

function jsonResponse(body: unknown, status = 200, statusText = "OK"): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText,
    headers: { "Content-Type": "application/json" },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** The URL and init of the one fetch call the test made. */
function onlyCall(): [string, RequestInit | undefined] {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0];
  return [url as string, init as RequestInit | undefined];
}

describe("deleteDocument", () => {
  it("sends DELETE to the document under its profile and returns the body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ deleted: 7 }));
    await expect(deleteDocument(3, 7)).resolves.toEqual({ deleted: 7 });
    const [url, init] = onlyCall();
    expect(url).toBe("/api/profiles/3/documents/7");
    expect(init?.method).toBe("DELETE");
  });

  it("rejects with the server's detail on a 404", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "document not found" }, 404, "Not Found"));
    await expect(deleteDocument(3, 99)).rejects.toThrow("API 404: document not found");
  });
});

describe("deleteProfile", () => {
  it("sends DELETE with the typed name URL-encoded in confirm_name", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ deleted: 3, applications: 2, documents: 1 }));
    await expect(deleteProfile(3, "Sam O'Neil & Co+")).resolves.toEqual({
      deleted: 3,
      applications: 2,
      documents: 1,
    });
    const [url, init] = onlyCall();
    expect(url).toBe("/api/profiles/3?confirm_name=Sam%20O'Neil%20%26%20Co%2B");
    expect(init?.method).toBe("DELETE");
  });

  it("rejects with the 422 detail when the name does not match", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "confirm_name must equal the person's name" }, 422, "Unprocessable Entity")
    );
    await expect(deleteProfile(3, "Sam")).rejects.toThrow(
      "API 422: confirm_name must equal the person's name"
    );
  });

  it("carries a 409's structured body in the error message", async () => {
    const body = {
      detail: {
        message: "Sam Lee has work in progress.",
        blocking: [{ id: 12, label: "Acme", status: "fetching" }],
      },
    };
    fetchMock.mockResolvedValue(jsonResponse(body, 409, "Conflict"));
    await expect(deleteProfile(3, "Sam Lee")).rejects.toThrow(`API 409: ${JSON.stringify(body)}`);
  });
});

describe("settings for a person", () => {
  it("getSettings() reads the app-wide settings, as before", async () => {
    fetchMock.mockResolvedValue(jsonResponse(SETTINGS));
    await expect(getSettings()).resolves.toEqual(SETTINGS);
    const [url, init] = onlyCall();
    expect(url).toBe("/api/settings");
    expect(init).toBeUndefined();
  });

  it("getSettings(id) reads that person's settings", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ...SETTINGS, page_size: "A4" }));
    await expect(getSettings(4)).resolves.toMatchObject({ page_size: "A4" });
    const [url] = onlyCall();
    expect(url).toBe("/api/settings?profile_id=4");
  });

  it("updateSettings(patch) writes the app-wide settings, as before", async () => {
    fetchMock.mockResolvedValue(jsonResponse(SETTINGS));
    await updateSettings({ page_size: "Letter" });
    const [url, init] = onlyCall();
    expect(url).toBe("/api/settings");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ page_size: "Letter" });
  });

  it("updateSettings(patch, id) writes that person's settings", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ...SETTINGS, page_size: "A4" }));
    await updateSettings({ page_size: "A4" }, 4);
    const [url, init] = onlyCall();
    expect(url).toBe("/api/settings?profile_id=4");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ page_size: "A4" });
  });
});
