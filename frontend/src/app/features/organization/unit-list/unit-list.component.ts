import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { OrganizationService, Unit } from '../../../core/services/organization.service';
import { UnitDialogComponent } from './unit-dialog.component';

@Component({
  selector: 'app-unit-list',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatSnackBarModule
  ],
  templateUrl: './unit-list.component.html',
  styleUrls: ['./unit-list.component.scss']
})
export class UnitList implements OnInit {
  private orgService = inject(OrganizationService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);

  displayedColumns: string[] = ['code', 'name', 'status', 'actions'];
  dataSource: Unit[] = [];

  ngOnInit(): void {
    this.loadData();
  }

  loadData() {
    this.orgService.getUnits().subscribe(data => this.dataSource = data);
  }

  openDialog(unit?: Unit) {
    const dialogRef = this.dialog.open(UnitDialogComponent, {
      width: '400px',
      data: unit || null
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        if (unit) {
          this.orgService.updateUnit(unit.id, result).subscribe(() => this.loadData());
        } else {
          this.orgService.createUnit(result).subscribe(() => this.loadData());
        }
      }
    });
  }

  deleteUnit(id: string) {
    if (confirm('Tem certeza que deseja inativar/remover esta unidade?')) {
      this.orgService.deleteUnit(id).subscribe(() => this.loadData());
    }
  }
}
