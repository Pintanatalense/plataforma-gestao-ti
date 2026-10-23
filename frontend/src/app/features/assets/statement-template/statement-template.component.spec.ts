import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { MatSnackBar } from '@angular/material/snack-bar';
import { StatementTemplateComponent } from './statement-template.component';

const URL = '/api/v1/assets/statement-template';
const payload = (over: object = {}) => ({
  template: '# Termo\n{{colaborador}}',
  is_default: true,
  default_template: '# Termo\n{{colaborador}}',
  fields: { colaborador: 'Nome do colaborador', patrimonio: 'Número de patrimônio' },
  blocks: { assinaturas: 'Campos de assinatura' },
  unknown_fields: [],
  ...over
});

describe('StatementTemplateComponent', () => {
  let fixture: ComponentFixture<StatementTemplateComponent>;
  let component: StatementTemplateComponent;
  let backend: HttpTestingController;
  let snack: { open: ReturnType<typeof vi.fn> };

  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };
  const el = (id: string) => fixture.nativeElement.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;
  const typeText = async (value: string) => {
    const area = el('template-text') as HTMLTextAreaElement;
    area.value = value;
    area.dispatchEvent(new Event('input'));
    await settle();
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [StatementTemplateComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([]), provideNoopAnimations()]
    }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(StatementTemplateComponent);
    component = fixture.componentInstance;
    snack = { open: vi.fn() };
    (component as unknown as { snackBar: MatSnackBar }).snackBar = snack as unknown as MatSnackBar;
    fixture.detectChanges();
  });

  it('mostra o modelo padrão e só habilita "Salvar" depois de uma alteração', async () => {
    backend.expectOne(URL).flush(payload());
    await settle();
    expect(el('template-status')?.textContent).toContain('padrão do sistema');
    expect((el('template-text') as HTMLTextAreaElement).value).toContain('{{colaborador}}');
    expect((el('template-save') as HTMLButtonElement).disabled).toBe(true);
    expect((el('template-reset') as HTMLButtonElement).disabled).toBe(true);

    await typeText('# Termo da empresa\n{{colaborador}}');
    expect((el('template-save') as HTMLButtonElement).disabled).toBe(false);
  });

  it('avisa sobre campos desconhecidos enquanto digita', async () => {
    backend.expectOne(URL).flush(payload());
    await settle();
    await typeText('{{colaborador}} {{matricula_errada}}');
    expect(el('template-unknown')?.textContent).toContain('matricula_errada');
    await typeText('{{colaborador}}');
    expect(el('template-unknown')).toBeNull();
  });

  it('salva o texto digitado e passa a mostrar "modelo próprio"', async () => {
    backend.expectOne(URL).flush(payload());
    await settle();
    await typeText('# Meu termo');
    (el('template-save') as HTMLButtonElement).click();

    const req = backend.expectOne(URL);
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ template: '# Meu termo' });
    req.flush(payload({ template: '# Meu termo', is_default: false }));
    await settle();

    expect(el('template-status')?.textContent).toContain('próprio da empresa');
    expect(snack.open).toHaveBeenCalledWith('Modelo do termo salvo.', 'OK', expect.anything());
    expect((el('template-save') as HTMLButtonElement).disabled).toBe(true);
  });

  it('falha ao salvar mostra a mensagem do servidor e mantém o texto', async () => {
    backend.expectOne(URL).flush(payload());
    await settle();
    await typeText('# Meu termo');
    (el('template-save') as HTMLButtonElement).click();
    backend.expectOne(URL).flush({ error: { message: 'O modelo do termo passou do limite.' } }, { status: 400, statusText: 'x' });
    await settle();

    expect(snack.open).toHaveBeenCalledWith('O modelo do termo passou do limite.', 'Fechar', expect.anything());
    expect((el('template-text') as HTMLTextAreaElement).value).toBe('# Meu termo');
  });

  it('volta ao modelo padrão depois de confirmar', async () => {
    backend.expectOne(URL).flush(payload({ template: '# Próprio', is_default: false }));
    await settle();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    (el('template-reset') as HTMLButtonElement).click();

    const req = backend.expectOne(URL);
    expect(req.request.method).toBe('DELETE');
    req.flush(payload());
    await settle();
    expect(el('template-status')?.textContent).toContain('padrão do sistema');
  });

  it('erro ao carregar aparece com "Tentar novamente" e sem editor', async () => {
    backend.expectOne(URL).flush({ error: { message: 'Sem permissão.' } }, { status: 403, statusText: 'x' });
    await settle();
    expect(el('state-error')).toBeTruthy();
    expect(el('template-text')).toBeNull();
  });
});
