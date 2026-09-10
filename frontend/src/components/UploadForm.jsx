import { useState } from "react";

export default function UploadForm({ onSubmit, loading }) {
  const [file, setFile] = useState(null);

  function handleSubmit(e) {
    e.preventDefault();
    if (file) onSubmit(file);
  }

  return (
    <form className="panel upload-row" onSubmit={handleSubmit}>
      <input
        type="file"
        accept="application/pdf"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      <button type="submit" disabled={!file || loading}>
        {loading ? "Processing..." : "Upload Invoice PDF"}
      </button>
    </form>
  );
}
