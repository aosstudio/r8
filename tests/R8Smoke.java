public final class R8Smoke {
  public static void main(String[] args) {
    if (args.length != 0) {
      Crash.raise();
    }
    System.out.println("R8 smoke test");
  }
}

final class Crash {
  static void raise() {
    throw new IllegalStateException("Retrace smoke test");
  }
}

final class Unused {
  static String unused() {
    return "This class must be removed.";
  }
}
