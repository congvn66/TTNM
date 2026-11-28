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
        <h1>Đã xảy ra lỗi</h1>
        <p>Tải lại trang để tiếp tục.</p>
        <button onClick={() => window.location.reload()}>Tải lại</button>
      </section>
    </main>;
  }
}
