import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { AssetService } from './asset.service';

const STATEMENT_URL = '/api/v1/assets/a1/responsibility-statement';

describe('AssetService: abrir o termo de responsabilidade', () => {
  let service: AssetService;
  let backend: HttpTestingController;
  let snack: { open: ReturnType<typeof vi.fn> };

  beforeEach(() => {
    snack = { open: vi.fn() };
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: MatSnackBar, useValue: snack }]
    });
    service = TestBed.inject(AssetService);
    backend = TestBed.inject(HttpTestingController);
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
  });

  afterEach(() => vi.restoreAllMocks());

  it('abre o documento em outra aba quando a API responde', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue({} as Window);
    service.openResponsibilityStatement('a1');
    backend.expectOne(STATEMENT_URL).flush(new Blob(['<html></html>']));
    expect(open).toHaveBeenCalledWith('blob:x', '_blank');
    expect(snack.open).not.toHaveBeenCalled();
  });

  it('avisa quando o navegador bloqueia a nova aba', () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    service.openResponsibilityStatement('a1');
    backend.expectOne(STATEMENT_URL).flush(new Blob(['<html></html>']));
    expect(snack.open).toHaveBeenCalledWith(expect.stringContaining('bloqueou a nova aba'), 'Fechar', expect.anything());
  });

  it('mostra erro quando a API falha (antes só ia para o console)', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue({} as Window);
    service.openResponsibilityStatement('a1');
    backend.expectOne(STATEMENT_URL).flush(new Blob(['x']), { status: 403, statusText: 'Forbidden' });
    expect(open).not.toHaveBeenCalled();
    expect(snack.open).toHaveBeenCalledTimes(1);
  });
});
