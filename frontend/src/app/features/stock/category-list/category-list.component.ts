import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators, FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatTableModule } from '@angular/material/table';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatChipsModule } from '@angular/material/chips';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { StockCategory, StockService } from '../../../core/services/stock.service';
import { apiErrorMessage } from '../../../core/http/api-error';

interface SpecFieldItem {
  name: string;
  required: boolean;
}

@Component({
  selector: 'app-stock-category-list',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    RouterModule,
    MatButtonModule,
    MatInputModule,
    MatFormFieldModule,
    MatTableModule,
    MatIconModule,
    MatTooltipModule,
    MatChipsModule,
    MatCheckboxModule,
    MatSnackBarModule
  ],
  template: `
    <div class="page-container">
      <div class="page-header">
        <div class="title-area">
          <div class="title-row">
            <button mat-icon-button routerLink="/stock" matTooltip="Voltar para Estoque" class="back-btn">
              <mat-icon>arrow_back</mat-icon>
            </button>
            <h1>Categorias de Estoque & Insumos</h1>
          </div>
          <p>Configure categorias personalizadas e campos técnicos para padronizar e agilizar o cadastro de materiais e suprimentos.</p>
        </div>
        <div class="header-actions">
          <button mat-stroked-button routerLink="/stock" class="nav-btn">
            <mat-icon>inventory_2</mat-icon>
            Ver Insumos
          </button>
        </div>
      </div>

      <div class="content-grid">
        <!-- Card de Formulário (Criar / Editar) -->
        <div class="form-card">
          <div class="card-header">
            <h3>{{ editingCategory ? 'Editar Categoria' : 'Nova Categoria' }}</h3>
            <p *ngIf="editingCategory" class="editing-subtitle">Editando: <strong>{{ editingCategory.name }}</strong></p>
          </div>

          <form [formGroup]="catForm" (ngSubmit)="onSubmit()" class="modern-form">
            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Nome da Categoria</mat-label>
              <input matInput formControlName="name" placeholder="Ex: Cabos & Conectores, Periféricos, Toners" required>
              <mat-error *ngIf="catForm.get('name')?.hasError('required')">O nome da categoria é obrigatório</mat-error>
            </mat-form-field>
            
            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Descrição (Opcional)</mat-label>
              <textarea matInput formControlName="description" rows="2" placeholder="Breve descrição dos materiais desta categoria..."></textarea>
            </mat-form-field>

            <!-- Seção de Campos Técnicos (Schema Dinâmico) -->
            <div class="specs-section">
              <div class="specs-header">
                <div class="specs-title">
                  <mat-icon>tune</mat-icon>
                  <span>Campos Técnicos (Especificações)</span>
                </div>
                <span class="specs-count">{{ specFields.length }} campo(s)</span>
              </div>
              <p class="specs-hint">
                Campos adicionais solicitados no momento do cadastro de cada insumo desta categoria.
              </p>

              <!-- Presets Rápidos -->
              <div class="presets-row">
                <span class="preset-label">Modelos rápidos:</span>
                <button type="button" mat-stroked-button (click)="applyPreset('peripherals')" class="preset-chip">
                  🖱️ Periféricos
                </button>
                <button type="button" mat-stroked-button (click)="applyPreset('cables')" class="preset-chip">
                  🔌 Cabos
                </button>
                <button type="button" mat-stroked-button (click)="applyPreset('toners')" class="preset-chip">
                  🖨️ Toners
                </button>
                <button type="button" mat-stroked-button (click)="applyPreset('hardware')" class="preset-chip">
                  ⚡ Peças/Hardware
                </button>
              </div>

              <!-- Lista de Campos Dinâmicos -->
              <div class="spec-fields-list" *ngIf="specFields.length > 0">
                <div class="spec-field-item" *ngFor="let field of specFields; let i = index">
                  <mat-form-field appearance="outline" class="field-name-input" subscriptSizing="dynamic">
                    <mat-label>Nome do Campo</mat-label>
                    <input matInput [(ngModel)]="field.name" [ngModelOptions]="{standalone: true}" placeholder="Ex: Metragem, Conector, Marca">
                  </mat-form-field>

                  <mat-checkbox [(ngModel)]="field.required" [ngModelOptions]="{standalone: true}" class="field-req-check">
                    Obrigatório
                  </mat-checkbox>

                  <button type="button" mat-icon-button color="warn" (click)="removeSpecField(i)" matTooltip="Remover campo" class="remove-field-btn">
                    <mat-icon>close</mat-icon>
                  </button>
                </div>
              </div>

              <div class="spec-empty-hint" *ngIf="specFields.length === 0">
                <mat-icon>playlist_add</mat-icon>
                <span>Nenhum campo técnico adicionado. Adicione campos ou clique em um modelo rápido.</span>
              </div>

              <button type="button" mat-stroked-button color="primary" (click)="addSpecField()" class="add-field-btn">
                <mat-icon>add</mat-icon>
                Adicionar Campo Técnico
              </button>
            </div>

            <!-- Live Preview -->
            <div class="live-preview-box" *ngIf="specFields.length > 0">
              <div class="preview-header">
                <mat-icon>visibility</mat-icon>
                <span>Pré-visualização do formulário no cadastro:</span>
              </div>
              <div class="preview-fields-grid">
                <div class="preview-field" *ngFor="let field of specFields">
                  <label>
                    {{ field.name || 'Campo sem nome' }}
                    <span class="req-star" *ngIf="field.required">*</span>
                  </label>
                  <div class="preview-input-sim">Preenchimento livre...</div>
                </div>
              </div>
            </div>

            <div class="form-actions">
              <button mat-button type="button" *ngIf="editingCategory" (click)="cancelEdit()" class="cancel-btn">
                Cancelar
              </button>
              <button mat-flat-button color="primary" type="submit" [disabled]="catForm.invalid" class="submit-btn">
                <mat-icon>{{ editingCategory ? 'save' : 'add' }}</mat-icon>
                {{ editingCategory ? 'Atualizar Categoria' : 'Criar Categoria' }}
              </button>
            </div>
          </form>
        </div>

        <!-- Card de Listagem de Categorias -->
        <div class="table-card">
          <div class="table-header">
            <h3>Categorias de Estoque Cadastradas</h3>
            <span class="badge-total">{{ categories.length }} categorias</span>
          </div>

          <table mat-table [dataSource]="categories" class="modern-table">
            <ng-container matColumnDef="name">
              <th mat-header-cell *matHeaderCellDef> Categoria </th>
              <td mat-cell *matCellDef="let element">
                <div class="category-info">
                  <span class="category-name">{{ element.name }}</span>
                  <span class="category-desc" *ngIf="element.description">{{ element.description }}</span>
                </div>
              </td>
            </ng-container>

            <ng-container matColumnDef="specs">
              <th mat-header-cell *matHeaderCellDef> Campos Técnicos </th>
              <td mat-cell *matCellDef="let element">
                <div class="specs-preview" *ngIf="getSpecKeys(element).length > 0">
                  <span class="spec-tag" *ngFor="let key of getSpecKeys(element) | slice:0:3">
                    {{ key }}
                  </span>
                  <span class="spec-tag more" *ngIf="getSpecKeys(element).length > 3">
                    +{{ getSpecKeys(element).length - 3 }}
                  </span>
                </div>
                <span class="no-specs" *ngIf="getSpecKeys(element).length === 0">
                  Sem campos específicos
                </span>
              </td>
            </ng-container>

            <ng-container matColumnDef="actions">
              <th mat-header-cell *matHeaderCellDef class="actions-header"> Ações </th>
              <td mat-cell *matCellDef="let element" class="actions-cell">
                <button mat-icon-button class="action-btn edit-btn" (click)="edit(element)" matTooltip="Editar Categoria">
                  <mat-icon>edit</mat-icon>
                </button>
                <button mat-icon-button class="action-btn delete-btn" (click)="deleteCategory(element)" matTooltip="Excluir Categoria">
                  <mat-icon>delete_outline</mat-icon>
                </button>
              </td>
            </ng-container>

            <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
            <tr mat-row *matRowDef="let row; columns: displayedColumns;"></tr>
            
            <tr class="mat-row" *matNoDataRow>
              <td class="mat-cell empty-state" [attr.colspan]="displayedColumns.length">
                <mat-icon>category</mat-icon>
                <p>Nenhuma categoria de estoque encontrada</p>
                <span>Utilize o formulário ao lado para cadastrar a primeira categoria.</span>
              </td>
            </tr>
          </table>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .page-container {
      display: flex;
      flex-direction: column;
      gap: 24px;
      width: 100%;
      box-sizing: border-box;
      animation: fadeIn 0.4s ease-out;
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .page-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--mat-sys-surface, #ffffff);
      padding: 24px 32px;
      border-radius: 20px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
      border: 1px solid var(--mat-sys-outline-variant, #e2e8f0);

      @media (max-width: 640px) {
        flex-direction: column;
        align-items: flex-start;
        gap: 16px;
        padding: 16px 20px;

        .header-actions {
          width: 100%;
          .nav-btn {
            width: 100%;
            justify-content: center;
          }
        }
      }

      .title-area {
        .title-row {
          display: flex;
          align-items: center;
          gap: 12px;

          .back-btn {
            color: var(--mat-sys-primary, #2563eb);
          }

          h1 {
            margin: 0;
            font-size: 28px;
            font-weight: 800;
            letter-spacing: -0.5px;
            color: #1e293b;
          }
        }

        p {
          margin: 6px 0 0;
          color: #64748b;
          font-size: 14px;
        }
      }

      .header-actions {
        display: flex;
        gap: 12px;

        .nav-btn {
          border-radius: 12px;
          font-weight: 600;
          height: 42px;
          mat-icon { margin-right: 6px; }
        }
      }
    }

    .content-grid {
      display: grid;
      grid-template-columns: 420px 1fr;
      gap: 24px;
      align-items: start;
    }

    @media (max-width: 1024px) {
      .content-grid {
        grid-template-columns: 1fr;
      }
    }

    .form-card, .table-card {
      background: var(--mat-sys-surface, #ffffff);
      border-radius: 20px;
      overflow: hidden;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
      border: 1px solid var(--mat-sys-outline-variant, #e2e8f0);
    }

    .table-card {
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }

    .form-card {
      padding: 28px;

      @media (max-width: 640px) {
        padding: 20px 16px;
      }
      
      .card-header {
        margin-bottom: 20px;
        h3 {
          margin: 0;
          font-size: 18px;
          font-weight: 700;
          color: #1e293b;
        }
        .editing-subtitle {
          margin: 4px 0 0;
          font-size: 13px;
          color: #2563eb;
        }
      }
    }

    .modern-form {
      display: flex;
      flex-direction: column;
      gap: 16px;

      .full-width {
        width: 100%;
      }
    }

    .specs-section {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 16px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 14px;

      .specs-header {
        display: flex;
        justify-content: space-between;
        align-items: center;

        .specs-title {
          display: flex;
          align-items: center;
          gap: 8px;
          font-weight: 700;
          font-size: 14px;
          color: #1e293b;
          mat-icon { color: #2563eb; font-size: 20px; width: 20px; height: 20px; }
        }

        .specs-count {
          font-size: 12px;
          font-weight: 600;
          color: #64748b;
          background: #e2e8f0;
          padding: 2px 8px;
          border-radius: 10px;
        }
      }

      .specs-hint {
        margin: 0;
        font-size: 12.5px;
        color: #64748b;
        line-height: 1.4;
      }

      .presets-row {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;

        .preset-label {
          font-size: 12px;
          font-weight: 600;
          color: #475569;
        }

        .preset-chip {
          border-radius: 12px;
          font-size: 12px;
          height: 32px;
          padding: 0 10px;
          border-color: #cbd5e1;
          color: #334155;
          &:hover {
            background-color: #eff6ff;
            color: #2563eb;
            border-color: #93c5fd;
          }
        }
      }

      .spec-fields-list {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }

      .spec-field-item {
        display: flex;
        align-items: center;
        gap: 12px;
        background: #ffffff;
        padding: 8px 12px;
        border-radius: 12px;
        border: 1px solid #e2e8f0;

        .field-name-input {
          flex: 1;
        }

        .field-req-check {
          font-size: 12.5px;
          font-weight: 500;
        }

        .remove-field-btn {
          width: 32px;
          height: 32px;
          mat-icon { font-size: 18px; width: 18px; height: 18px; }
        }
      }

      .spec-empty-hint {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px;
        background: #ffffff;
        border: 1px dashed #cbd5e1;
        border-radius: 12px;
        color: #64748b;
        font-size: 13px;
        mat-icon { font-size: 18px; width: 18px; height: 18px; }
      }

      .add-field-btn {
        border-radius: 12px;
        font-weight: 600;
        height: 38px;
        mat-icon { margin-right: 4px; font-size: 18px; width: 18px; height: 18px; }
      }
    }

    .live-preview-box {
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-radius: 14px;
      padding: 16px;

      .preview-header {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 12.5px;
        font-weight: 700;
        color: #1e40af;
        margin-bottom: 12px;
        mat-icon { font-size: 18px; width: 18px; height: 18px; }
      }

      .preview-fields-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
        gap: 10px;

        .preview-field {
          display: flex;
          flex-direction: column;
          gap: 4px;

          label {
            font-size: 11.5px;
            font-weight: 600;
            color: #334155;

            .req-star {
              color: #ef4444;
            }
          }

          .preview-input-sim {
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 11px;
            color: #94a3b8;
          }
        }
      }
    }

    .form-actions {
      display: flex;
      justify-content: flex-end;
      gap: 12px;
      margin-top: 8px;

      .cancel-btn {
        border-radius: 12px;
        font-weight: 600;
      }

      .submit-btn {
        border-radius: 12px;
        font-weight: 600;
        height: 42px;
        mat-icon { margin-right: 6px; }
      }
    }

    .table-card {
      padding: 24px;

      .table-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 18px;

        h3 {
          margin: 0;
          font-size: 18px;
          font-weight: 700;
          color: #1e293b;
        }

        .badge-total {
          background: #eff6ff;
          color: #2563eb;
          font-weight: 700;
          font-size: 12px;
          padding: 4px 10px;
          border-radius: 20px;
        }
      }

      .modern-table {
        width: 100%;
        min-width: 520px;
        border-collapse: separate;
        border-spacing: 0;

        th {
          font-size: 12px;
          font-weight: 700;
          color: #64748b;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          padding: 12px 16px;
          border-bottom: 1px solid #e2e8f0;
        }

        td {
          padding: 14px 16px;
          border-bottom: 1px solid #f1f5f9;
        }

        .category-info {
          display: flex;
          flex-direction: column;
          gap: 2px;

          .category-name {
            font-weight: 600;
            color: #0f172a;
            font-size: 14px;
          }

          .category-desc {
            font-size: 12px;
            color: #64748b;
          }
        }

        .specs-preview {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;

          .spec-tag {
            background: #f1f5f9;
            color: #475569;
            font-size: 11px;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 6px;
            border: 1px solid #e2e8f0;

            &.more {
              background: #eff6ff;
              color: #2563eb;
              border-color: #bfdbfe;
            }
          }
        }

        .no-specs {
          font-size: 12px;
          color: #94a3b8;
          font-style: italic;
        }

        .actions-header {
          text-align: right;
        }

        .actions-cell {
          text-align: right;

          .action-btn {
            margin-left: 4px;
            &.edit-btn { color: #2563eb; }
            &.delete-btn { color: #ef4444; }
          }
        }

        .empty-state {
          text-align: center;
          padding: 48px 16px;
          color: #64748b;

          mat-icon {
            font-size: 40px;
            width: 40px;
            height: 40px;
            color: #94a3b8;
            margin-bottom: 12px;
          }

          p {
            margin: 0;
            font-weight: 600;
            font-size: 15px;
            color: #1e293b;
          }

          span {
            font-size: 13px;
            color: #64748b;
          }
        }
      }
    }
  `]
})
export class StockCategoryListComponent implements OnInit {
  private fb = inject(FormBuilder);
  private stockService = inject(StockService);
  private snackBar = inject(MatSnackBar);

  displayedColumns: string[] = ['name', 'specs', 'actions'];
  categories: StockCategory[] = [];
  editingCategory: StockCategory | null = null;
  specFields: SpecFieldItem[] = [];

  catForm: FormGroup = this.fb.group({
    name: ['', Validators.required],
    description: ['']
  });

  ngOnInit(): void {
    this.loadData();
  }

  loadData(): void {
    this.stockService.getCategories().subscribe({
      next: (cats) => (this.categories = cats),
      error: (err) => {
        console.error('Erro ao carregar categorias de estoque:', err);
        this.snackBar.open('Erro ao carregar categorias de estoque.', 'Fechar', { duration: 4000 });
      }
    });
  }

  getSpecKeys(cat: StockCategory): string[] {
    if (!cat.spec_schema) return [];
    return Object.keys(cat.spec_schema);
  }

  addSpecField(): void {
    this.specFields.push({ name: '', required: false });
  }

  removeSpecField(index: number): void {
    this.specFields.splice(index, 1);
  }

  applyPreset(type: 'peripherals' | 'cables' | 'toners' | 'hardware'): void {
    if (type === 'peripherals') {
      this.specFields = [
        { name: 'Tipo de Periférico', required: true },
        { name: 'Marca / Fabricante', required: false },
        { name: 'Conexão (USB, Bluetooth, etc.)', required: false },
        { name: 'Cor / Acabamento', required: false }
      ];
    } else if (type === 'cables') {
      this.specFields = [
        { name: 'Tipo de Cabo', required: true },
        { name: 'Comprimento (metros)', required: false },
        { name: 'Conectores das Pontas', required: false },
        { name: 'Blindagem / Padrão', required: false }
      ];
    } else if (type === 'toners') {
      this.specFields = [
        { name: 'Modelo do Suprimento', required: true },
        { name: 'Impressoras Compatíveis', required: true },
        { name: 'Cor da Tinta / Toner', required: false },
        { name: 'Rendimento Estimado', required: false }
      ];
    } else if (type === 'hardware') {
      this.specFields = [
        { name: 'Tipo de Peça (RAM, SSD, Fonte)', required: true },
        { name: 'Capacidade / Frequência', required: false },
        { name: 'Interface / Encaixe', required: false },
        { name: 'Marca / Fabricante', required: false }
      ];
    }
  }

  edit(cat: StockCategory): void {
    this.editingCategory = cat;
    this.catForm.patchValue({
      name: cat.name,
      description: cat.description || ''
    });

    this.specFields = [];
    if (cat.spec_schema) {
      for (const [key, val] of Object.entries(cat.spec_schema)) {
        const isReq = typeof val === 'object' && val !== null ? (val as any).required ?? false : false;
        const label = typeof val === 'object' && val !== null && (val as any).label ? (val as any).label : key;
        this.specFields.push({ name: label, required: !!isReq });
      }
    }
  }

  cancelEdit(): void {
    this.editingCategory = null;
    this.catForm.reset();
    this.specFields = [];
  }

  onSubmit(): void {
    if (this.catForm.invalid) return;

    // Constrói o spec_schema JSON
    const specSchema: Record<string, any> = {};
    for (const field of this.specFields) {
      const cleanName = field.name.trim();
      if (cleanName) {
        specSchema[cleanName] = {
          type: 'string',
          required: field.required,
          label: cleanName
        };
      }
    }

    const payload: Partial<StockCategory> = {
      name: this.catForm.value.name.trim(),
      description: this.catForm.value.description ? this.catForm.value.description.trim() : null,
      spec_schema: specSchema
    };

    if (this.editingCategory) {
      this.stockService.updateCategory(this.editingCategory.id, payload).subscribe({
        next: () => {
          this.snackBar.open('Categoria atualizada com sucesso!', 'Fechar', { duration: 3000 });
          this.loadData();
          this.cancelEdit();
        },
        error: (err) => {
          console.error('Erro ao atualizar categoria:', err);
          const msg = apiErrorMessage(err, 'Erro ao atualizar categoria.');
          this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        }
      });
    } else {
      this.stockService.createCategory(payload).subscribe({
        next: () => {
          this.snackBar.open('Categoria criada com sucesso!', 'Fechar', { duration: 3000 });
          this.loadData();
          this.cancelEdit();
        },
        error: (err) => {
          console.error('Erro ao criar categoria:', err);
          const msg = apiErrorMessage(err, 'Erro ao criar categoria.');
          this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        }
      });
    }
  }

  deleteCategory(cat: StockCategory): void {
    if (!confirm(`Deseja realmente desativar a categoria "${cat.name}"?`)) {
      return;
    }

    this.stockService.deleteCategory(cat.id).subscribe({
      next: () => {
        this.snackBar.open(`Categoria "${cat.name}" removida.`, 'Fechar', { duration: 3000 });
        this.loadData();
        if (this.editingCategory?.id === cat.id) {
          this.cancelEdit();
        }
      },
      error: (err) => {
        console.error('Erro ao remover categoria:', err);
        const msg = apiErrorMessage(err, 'Erro ao remover categoria.');
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
      }
    });
  }
}
