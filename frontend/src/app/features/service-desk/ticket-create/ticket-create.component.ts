import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, FormsModule, ReactiveFormsModule, Validators, FormControl } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatDividerModule } from '@angular/material/divider';
import { MatChipsModule } from '@angular/material/chips';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { HttpResponse } from '@angular/common/http';
import { filter, firstValueFrom } from 'rxjs';

import {
  TicketService,
  TicketCategory,
  CategoryFormField,
  ChildTicketSpec,
  TicketTemplate,
  newIdempotencyKey
} from '../ticket.service';
import { Employee, OrganizationService } from '../../../core/services/organization.service';
import { Asset, AssetService } from '../../../core/services/asset.service';
import { AuthService } from '../../../core/auth/auth.service';
import { AttachmentsService } from '../../../core/services/attachments.service';
import { apiErrorMessage } from '../../../core/http/api-error';

@Component({
  selector: 'app-ticket-create',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    RouterModule,
    MatButtonModule,
    MatInputModule,
    MatSelectModule,
    MatIconModule,
    MatCheckboxModule,
    MatDividerModule,
    MatChipsModule,
    MatSnackBarModule,
    MatProgressBarModule,
    MatTooltipModule
  ],
  templateUrl: './ticket-create.component.html',
  styleUrls: ['./ticket-create.component.scss']
})
export class TicketCreateComponent implements OnInit {
  private fb = inject(FormBuilder);
  private ticketService = inject(TicketService);
  private assetService = inject(AssetService);
  private attachmentsService = inject(AttachmentsService);
  private orgService = inject(OrganizationService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  private snackBar = inject(MatSnackBar);
  public authService = inject(AuthService);

  ticketForm: FormGroup;
  customFieldsForm: FormGroup;
  categories: TicketCategory[] = [];
  availableAssets: Asset[] = [];
  selectedCategory: TicketCategory | null = null;
  prerequisiteFields: CategoryFormField[] = [];

  selectedFiles: File[] = [];

  // Chamados vinculados (ADR-026): subchamados opcionais, pré-preenchidos por um modelo.
  templates: TicketTemplate[] = [];
  selectedTemplateId: string | null = null;
  childSpecs: ChildTicketSpec[] = [];
  // Abertura em nome de outra pessoa (permissão service_desk.tickets.create_on_behalf).
  canOpenOnBehalf = false;
  employees: Employee[] = [];
  requesterId: string | null = null;
  // Uma chave por intenção de envio: um clique repetido ou uma nova tentativa não duplica o chamado.
  private idempotencyKey = newIdempotencyKey();
  isSubmitting = false;
  uploadProgressText = '';

  constructor() {
    this.ticketForm = this.fb.group({
      title: ['', Validators.required],
      description: ['', Validators.required],
      priority: ['LOW', Validators.required],
      category_id: [null],
      asset_id: [null]
    });

    this.customFieldsForm = this.fb.group({});
  }

  ngOnInit() {
    const preselectedAssetId = this.route.snapshot.queryParamMap.get('asset_id');

    this.ticketService.getCategories().subscribe({
      next: (data) => (this.categories = data),
      error: (err) => console.error(err)
    });

    if (this.authService.hasPermission('assets.read')) {
      this.assetService.getAssets().subscribe({
        next: (assets) => {
          this.availableAssets = assets;
          if (preselectedAssetId && this.availableAssets.some((a) => a.id === preselectedAssetId)) {
            this.ticketForm.patchValue({ asset_id: preselectedAssetId });
          }
        },
        error: () => {}
      });
    } else {
      this.assetService.getMyAssets().subscribe({
        next: (assets) => {
          this.availableAssets = assets;
          if (preselectedAssetId && this.availableAssets.some((a) => a.id === preselectedAssetId)) {
            this.ticketForm.patchValue({ asset_id: preselectedAssetId });
          }
        },
        error: () => {}
      });
    }

    this.ticketService.listTemplates().subscribe({
      next: (templates) => (this.templates = templates),
      error: () => {}
    });

    this.canOpenOnBehalf = this.authService.hasPermission('service_desk.tickets.create_on_behalf');
    if (this.canOpenOnBehalf) {
      this.orgService.getEmployees().subscribe({
        next: (emps) => (this.employees = emps),
        error: () => (this.canOpenOnBehalf = false)  // sem acesso à lista de colaboradores: abre para si
      });
    }

    this.ticketForm.get('category_id')?.valueChanges.subscribe((catId) => {
      this.onCategorySelected(catId);
    });
  }

  onCategorySelected(catId: string | null) {
    if (!catId) {
      this.selectedCategory = null;
      this.prerequisiteFields = [];
      this.customFieldsForm = this.fb.group({});
      return;
    }

    const cat = this.categories.find(c => c.id === catId);
    this.selectedCategory = cat || null;
    this.prerequisiteFields = cat?.form_schema || [];

    const group: Record<string, FormControl> = {};
    for (const field of this.prerequisiteFields) {
      const validators = [];
      if (field.required) {
        if (field.type === 'checkbox') {
          validators.push(Validators.requiredTrue);
        } else {
          validators.push(Validators.required);
        }
      }
      group[field.id] = new FormControl(
        field.type === 'checkbox' ? false : '',
        validators
      );
    }
    this.customFieldsForm = this.fb.group(group);
  }

  applyTemplate(templateId: string | null): void {
    this.selectedTemplateId = templateId;
    const template = this.templates.find((t) => t.id === templateId);
    if (!template) return;
    this.childSpecs = template.items.map((item) => ({
      category_id: item.category_id,
      title: item.title,
      description: item.description,
      is_required: item.is_required,
      responsible_sector_id: item.responsible_sector_id || null,
      custom_fields: { ...(item.default_custom_fields || {}) }
    }));
  }

  addChildRow(): void {
    this.childSpecs.push({ category_id: '', title: '', description: '', is_required: true });
  }

  removeChildRow(index: number): void {
    this.childSpecs.splice(index, 1);
  }

  childrenValid(): boolean {
    return this.childSpecs.every((s) => s.category_id && s.title.trim() && s.description.trim());
  }

  onFilesSelected(event: any): void {
    const files: FileList = event.target.files;
    if (files) {
      for (let i = 0; i < files.length; i++) {
        this.selectedFiles.push(files[i]);
      }
    }
    event.target.value = null;
  }

  removeSelectedFile(index: number): void {
    this.selectedFiles.splice(index, 1);
  }

  formatFileSize(bytes: number): string {
    return this.attachmentsService.formatBytes(bytes);
  }

  onSubmit() {
    if (this.ticketForm.invalid) {
      this.ticketForm.markAllAsTouched();
      return;
    }

    if (this.prerequisiteFields.length > 0 && this.customFieldsForm.invalid) {
      this.customFieldsForm.markAllAsTouched();
      this.snackBar.open(
        'Atenção: Todos os pré-requisitos obrigatórios desta categoria devem ser preenchidos.',
        'Fechar',
        { duration: 5000 }
      );
      return;
    }

    if (!this.childrenValid()) {
      this.snackBar.open('Cada subchamado precisa de categoria, título e descrição.', 'Fechar', { duration: 5000 });
      return;
    }

    this.isSubmitting = true;
    this.uploadProgressText = '';

    const val = this.ticketForm.value;
    const customFieldsVal = this.customFieldsForm.value;

    const payload: any = {
      title: val.title,
      description: val.description,
      priority: val.priority,
      category_id: val.category_id || undefined,
      asset_ids: val.asset_id ? [val.asset_id] : [],
      custom_fields: customFieldsVal,
      requester_id: this.canOpenOnBehalf && this.requesterId ? this.requesterId : undefined,
      template_id: this.selectedTemplateId || undefined,
      children: this.childSpecs
    };

    this.ticketService.createTicket(payload, this.idempotencyKey).subscribe({
      next: async (ticket) => {
        this.idempotencyKey = newIdempotencyKey();
        const failedUploads: string[] = [];
        if (this.selectedFiles.length > 0) {
          this.uploadProgressText = `Enviando ${this.selectedFiles.length} anexo(s)...`;
          for (let i = 0; i < this.selectedFiles.length; i++) {
            const f = this.selectedFiles[i];
            try {
              // uploadFile() emite eventos (Sent, progresso, resposta). `firstValueFrom` sem filtro resolvia no primeiro
              // evento (Sent) e CANCELAVA o upload: o chamado era criado e o anexo nunca chegava ao servidor.
              await firstValueFrom(
                this.attachmentsService.uploadFile(f, 'TICKET', ticket.id).pipe(filter((e) => e instanceof HttpResponse))
              );
            } catch (err) {
              console.error('Erro ao enviar anexo:', f.name, err);
              failedUploads.push(f.name);
            }
          }
        }

        this.isSubmitting = false;
        if (failedUploads.length > 0) {
          // o chamado existe, mas nem todos os anexos foram: não anuncia sucesso total
          this.snackBar.open(
            `Chamado aberto, mas ${failedUploads.length} anexo(s) NÃO foram enviados: ${failedUploads.join(', ')}. Anexe de novo pela tela do chamado.`,
            'Fechar',
            { duration: 10000 }
          );
        } else {
          const msg = this.selectedFiles.length > 0
            ? `Chamado aberto com sucesso com ${this.selectedFiles.length} anexo(s) vinculado(s)!`
            : 'Chamado aberto com sucesso!';
          this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        }
        this.router.navigate(['/service-desk', ticket.id]);
      },
      error: (err) => {
        this.isSubmitting = false;
        console.error(err);
        const msg = apiErrorMessage(err, 'Erro ao abrir chamado. Verifique os pré-requisitos.');
        this.snackBar.open(msg, 'Fechar', { duration: 6000 });
      }
    });
  }
}
