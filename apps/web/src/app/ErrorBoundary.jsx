import { Component } from "react";

export default class ErrorBoundary extends Component {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error) {
    console.error("SourceLens UI boundary", error);
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    return <main className="connection-screen" role="alert">
      <section className="connection-card">
        <span className="eyebrow">GIAO DIỆN TẠM DỪNG</span>
        <h1>Không thể hiển thị workspace</h1>
        <p>Trạng thái tài liệu vẫn được lưu ở backend. Tải lại trang để khôi phục giao diện.</p>
        <button onClick={() => window.location.reload()}>Tải lại</button>
      </section>
    </main>;
  }
}
