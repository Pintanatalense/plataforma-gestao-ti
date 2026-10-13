import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { AssetDetailComponent } from './asset-detail.component';
import { Attachment } from '../../../core/services/attachments.service';

describe('AssetDetailComponent', () => {
  let component: AssetDetailComponent;
  let fixture: ComponentFixture<AssetDetailComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AssetDetailComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideAnimationsAsync()
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(AssetDetailComponent);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should detect when signed responsibility statement is attached', () => {
    expect(component.hasSignedStatement).toBe(false);

    const mockAttachments: Attachment[] = [
      {
        id: '1',
        filename: 'manual_usuario.docx',
        content_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        size_bytes: 12345,
        entity_type: 'ASSET',
        entity_id: 'a1',
        uploaded_by_id: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
      }
    ];

    component.attachments = mockAttachments;
    expect(component.hasSignedStatement).toBe(false);

    const signedDoc: Attachment = {
      id: '2',
      filename: 'termo_responsabilidade_assinado.pdf',
      content_type: 'application/pdf',
      size_bytes: 54321,
      entity_type: 'ASSET',
      entity_id: 'a1',
      uploaded_by_id: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    };

    component.attachments = [...mockAttachments, signedDoc];
    expect(component.hasSignedStatement).toBe(true);
    expect(component.signedStatementFile?.id).toBe('2');
  });

  it('should return employee and unit display names correctly', () => {
    expect(component.getEmployeeName(null)).toBe('Nenhum (Em Estoque)');
    expect(component.getUnitName(undefined)).toBe('N/A');
  });
});
