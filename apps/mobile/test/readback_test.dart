import 'package:accnomos_mobile/models/readback.dart';
import 'package:flutter_test/flutter_test.dart';

// The same cases as the web app's apps/web/e2e/readback.spec.ts.
void main() {
  test('whole numbers read in British English', () {
    expect(wholeInWords(0), 'zero');
    expect(wholeInWords(40), 'forty');
    expect(wholeInWords(105), 'one hundred and five');
    expect(wholeInWords(1005), 'one thousand and five');
    expect(wholeInWords(1405), 'one thousand, four hundred and five');
    expect(wholeInWords(2500000), 'two million, five hundred thousand');
  });

  test('money reads as pounds and pence', () {
    expect(penceInWords(4000), 'forty pounds');
    expect(penceInWords(1400), 'fourteen pounds');
    expect(penceInWords(4050), 'forty pounds and fifty pence');
    expect(penceInWords(100), 'one pound');
    expect(penceInWords(5), 'five pence');
    expect(penceInWords(-250), 'minus two pounds and fifty pence');
  });

  test('quantities keep their decimals', () {
    expect(quantityInWords('12.5'), 'twelve point five');
    expect(quantityInWords('3.00'), 'three');
    expect(quantityInWords('0.25'), 'zero point two five');
  });

  test('each spoken card reads back the figure it acts on', () {
    final miles = readBack('log_mileage', {'miles': '14'});
    expect(miles.single.figure, '14 miles');
    expect(miles.single.words, 'fourteen miles');
    expect(readBack('log_timesheet', {'hours': '1'}).single.words, 'one hour');
    final split = readBack('log_timesheet', {
      'hours': '2',
      'overtime_hours': '1',
      'cost_pence': 3300,
    });
    expect(split.map((l) => l.figure), ['2 hours', '1 hour', '£33.00']);
    final inv = readBack('create_invoice', {
      'lines': [
        {'unit_price_pence': 45000},
      ],
      'total_pence': 54000,
    });
    expect(inv.map((l) => l.label), ['Price each', 'Total']);
    expect(inv.last.figure, '£540.00');
    expect(inv.last.words, 'five hundred and forty pounds');
    expect(
      readBack('match_bank_line', {'amount_pence': 123456}).single.figure,
      '£1,234.56',
    );
    expect(readBack('close_month', {}), isEmpty);
    final box = spokenReadBack('log 14 miles to the yard', miles);
    expect(box, contains('We heard: “log 14 miles to the yard”'));
    expect(box, contains('Distance: 14 miles (fourteen miles)'));
  });
}
