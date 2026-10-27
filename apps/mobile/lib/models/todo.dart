/// One to-do from `GET /todos` (services/runtime/app/todos.py).
class TodoItem {
  TodoItem({
    required this.id,
    required this.text,
    this.due,
  });

  final String id;
  final String text;

  /// `YYYY-MM-DD`, or null when the to-do has no due date.
  final String? due;

  factory TodoItem.fromJson(Map<String, dynamic> json) => TodoItem(
        id: (json['id'] ?? '').toString(),
        text: (json['text'] ?? '').toString(),
        due: json['due']?.toString(),
      );

  static List<TodoItem> listFromJson(List<Map<String, dynamic>> raw) =>
      [for (final j in raw) TodoItem.fromJson(j)];

  /// Labelled demo rows for the signed-out card. Fictional, like the
  /// Review screen's samples.
  static List<TodoItem> get samples => [
        TodoItem(id: 'sample-1', text: 'Chase INV-0041 (12 days overdue)', due: '2026-10-15'),
        TodoItem(id: 'sample-2', text: 'File the VAT return for Jul–Sep', due: '2026-11-07'),
        TodoItem(id: 'sample-3', text: 'Match the October bank lines'),
      ];
}
