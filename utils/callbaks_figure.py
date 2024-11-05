
import plotly.graph_objects as go
import pandas as pd 
from npd_wraper import field
#import dash_html_components as html
from dash import html



def fig_plot_oil(df_selection):
    fig={
        'data':[
            go.Scatter(
                x=df_selection.index,
                y=df_selection["prfPrdProducedWaterInFieldMillSm3"].div(
                    df_selection["prfPrdProducedWaterInFieldMillSm3"] +
                    df_selection['prfPrdOilNetMillSm3']),
                name="Water cut",
                mode="lines+markers",
                line={'color':'blue'},
                yaxis='y2'
            ),

            go.Scatter(
                x=df_selection.index,
                y=df_selection['prfPrdOilNetMillSm3'] / 30.5 * 1E6,
                name="Free Oil",
                mode='lines',
                fillcolor="green",
                line={'color': 'green'},
                yaxis='y1',
                stackgroup='one'
            ),
            go.Scatter(
                x=df_selection.index,
                y=df_selection['prfPrdNGLNetMillSm3'] / 30.5 * 1E6,
                name="NGL",
                mode='lines',
                fillcolor="orange",
                line={'color': 'orange'},
                yaxis='y1',
                stackgroup='one'
            )

        ],
        'layout':go.Layout(
            title='Liquid historical production',
            yaxis1={'title': 'Liquid production rate sm3/D'},
            yaxis2={'side': "right", "overlaying": "y"},
            hovermode="x unified",
            legend_orientation="h"
        )
    }
    fig['layout']['yaxis2'].update(title='', range=[0, 1], tickformat=',.0%', autorange=False)
    fig['layout']['yaxis1'].update(range=[0,max((df_selection['prfPrdOilNetMillSm3'] / 30.5 * 1E6)+
                                                df_selection['prfPrdNGLNetMillSm3'] / 30.5 * 1E6)])
    return fig


def fig_plot_gas(df_selection):
    fig ={
        'data':[
            go.Scatter(
            x = df_selection.index,
            y = df_selection['prfPrdCondensateNetMillSm3'] / 30.5 * 1E6,
            name = 'Condensate',
            mode = 'lines',
            fillcolor = "pink",
            fill = 'tozeroy',
            line = {'color': 'pink'}
            ),
            go.Scatter(
                x=df_selection.index,
                y=df_selection['prfPrdGasNetBillSm3'] / 30.5 * 1E9,
                name='Free Gas',
                mode='lines',
                fillcolor="red",
                fill='tozeroy',
                line={'color': 'red'}
            )
        ],
        'layout':go.Layout(
            title='Gas plot',
            yaxis={'title':'Gas produce rate Msm3/D'},
            hovermode="x unified"
        )
    }
    return fig

def update_tail_production(df_selection):
    #df_selection.set_index('date', inplace=True)
    pd.options.display.float_format = '{:,.3f}'.format
    cols = ["prfPrdOilNetMillSm3", "prfPrdGasNetBillSm3",
            "prfPrdNGLNetMillSm3", "prfPrdCondensateNetMillSm3", "prfPrdOeNetMillSm3",
            "prfPrdProducedWaterInFieldMillSm3"]
    temp = df_selection[cols].reset_index().tail(12)
    
    temp.columns = ["Date", "Oil [Sm3/D]", "Gas [Msm3/D]", "NGL [Sm3/D]", "Condensate [Sm3/D]", "OE [Sm3/D]",
                    "Water [Sm3/D]"]
    # compute daily average
    temp["Oil [Sm3/D]"] = temp["Oil [Sm3/D]"] / 30.5 * 1E6
    temp["Gas [Msm3/D]"] = temp["Gas [Msm3/D]"] / 30.5 * 1E9
    temp["NGL [Sm3/D]"] = temp["NGL [Sm3/D]"] / 30.5 * 1E6
    temp["Condensate [Sm3/D]"] = temp["Condensate [Sm3/D]"] / 30.5 * 1E6
    temp["OE [Sm3/D]"] = temp["OE [Sm3/D]"] / 30.5 * 1E6
    temp["Water [Sm3/D]"] = temp["Water [Sm3/D]"] / 30.5 * 1E6
    temp['Date'] = temp['Date'].dt.strftime('%m.%Y')
    temp.set_index("Date", inplace=True)

    mapper = {"Oil [Sm3/D]": '{0:.2f}',
              "Gas [Msm3/D]": '{0:.2e}',
              "NGL [Sm3/D]": '{0:.2f}',
              "Condensate [Sm3/D]": '{0:.2f}',
              "OE [Sm3/D]": '{0:.2f}',
              "Water [Sm3/D]": '{0:.2f}'}

    temp = temp.apply(lambda x: x.apply(mapper[x.name].format))

    return temp


def get_field_info(selected_field):
    df_info=field().get_field_overview()
    df_info=df_info[df_info.fldName == selected_field]
    df_inplace=field().get_field_inplace_volume()
    df_inplace=df_inplace[df_inplace.fldName ==selected_field]
    df_production=field().get_field_production_yearly()
    df_production=df_production[df_production['prfInformationCarrier']==selected_field]
    df_overview=field().get_field_overview()
    df_overview = df_overview[df_overview.fldName == selected_field]

    df_production =df_production[['prfPrdOilNetMillSm3','prfPrdGasNetBillSm3']]

    for col in df_production.columns:
        df_production[col]=df_production[col].astype('float')

    df_production=df_production.cumsum(axis=0)
    #print(df_inplace)
    if float(df_inplace.fldInplaceOil.values[0])>0:
        oil_rf= df_production['prfPrdOilNetMillSm3'].max()/float(df_inplace.fldInplaceOil.values[0])
    else:
        oil_rf =0
    if float(df_inplace.fldInplaceFreeGas.values[0])>0:
        gas_rf= df_production.prfPrdGasNetBillSm3.max()/float(df_inplace.fldInplaceFreeGas.values[0])
    else:
        gas_rf=0
    
    s = '''
    * __Status__:  %s  
    * __Area__:    %s  
    * __Discovery Well__: %s
    * __Discovery_date__: %s 
    * __Operator__: %s 
    * __Inplace Volume__: Oil : %.1f Msm3 , Gas : %.1f Gsm3

    * __Recovery Factor__: Oil : %.2f , Gas: %.2f
    ''' % (str(df_info.fldCurrentActivitySatus.values[0]),
           str(df_info.fldMainArea.values[0]),
           str(df_overview.wlbName.values[0]),
           str(df_info.wlbCompletionDate.values[0]),
           str(df_info.cmpLongName.values[0]),
           float(df_inplace.fldInplaceOil.values[0]),
           float(df_inplace.fldInplaceFreeGas.values[0]),
           oil_rf,gas_rf)
    return s


def field_map(selected_field):
    df_info = field().get_field_overview()
    df_info = df_info[df_info.fldName == selected_field]
    iframe_url="https://factmaps.sodir.no/factmaplink/?entity=field&npdid=%i&shellMode=handheld"%int(df_info.fldNpdidField.values[0])
    # HTML code for embedding the iframe
    iframe_html = f'<iframe width="360" height="315" src="{iframe_url}" frameborder="0" allowfullscreen></iframe>'
    return iframe_html

def callback_plot_reserve(selected_field):
    #get total recoverable and reserves
    df_info= field().get_field_reserves()
    df_info=df_info[df_info.fldName ==selected_field]
    recoverable = float(df_info["fldRecoverableOil"])
    remaining = float(df_info["fldRemainingOil"])
    #get production volume
    df_prod=field().get_field_production_yearly()
    df_prod=df_prod[df_prod.prfInformationCarrier == selected_field]
    df_prod['prfPrdOilNetMillSm3']=df_prod['prfPrdOilNetMillSm3'].astype('float32')
    produced= float(df_prod.prfPrdOilNetMillSm3.sum())
    #get in place volume
    df_info = field().get_field_inplace_volume()
    df_info =df_info[df_info.fldName == selected_field]
    inplace= float(df_info["fldInplaceOil"])

    fig=go.Figure(go.Indicator(
        mode='gauge+number',
        value=produced+remaining,
        domain={'x':[0,1], 'y':[0,1]},
        title= {'text':'Oil produced volume Msm3'},
        delta={'reference':produced, 'increasing':{'color':'#618152'}},
        gauge={
            'axis': {'range': [None, inplace], 'tickwidth': 1, 'tickcolor': "darkblue"},
            'bar': {'color': "green"},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "gray",
            'steps': [
                {'range': [0, produced], 'color': '#0F9768'},
                {'range': [produced, produced + remaining], 'color': '#52CB19'}],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': recoverable}}))
    return fig

def callback_plot_gas(selected_field):
    #get totalrecoverable and reserves
    df_info = field().get_field_reserves()
    df_info = df_info[df_info.fldName == selected_field]
    recoverable=float(df_info["fldRecoverableGas"])
    remaining= float(df_info["fldRemainingGas"])
    #get produced volume
    df_prod=field().get_field_production_yearly()
    df_prod = df_prod[df_prod.prfInformationCarrier== selected_field]
    df_prod['prfPrdGasNetBillSm3']=df_prod['prfPrdGasNetBillSm3'].astype('float32')
    produced= float(df_prod.prfPrdGasNetBillSm3.sum())
    # get inplace volume
    df_info = field().get_field_inplace_volume()
    df_info = df_info[df_info.fldName == selected_field]
    inplace=float(df_info["fldInplaceAssGas"])+float(df_info["fldInplaceFreeGas"])

    fig=go.Figure(go.Indicator(
        mode = "gauge+number",
        value = produced+remaining,
        domain = {'x': [0, 1], 'y': [0, 1]},
        title = {'text': "Gas produced volumes Gsm3"},
        delta = {'reference': produced, 'increasing': {'color': "#D0297F"}},
        gauge = {
            'axis': {'range': [None, inplace], 'tickwidth': 1, 'tickcolor': "darkblue"},
            'bar': {'color': "red"},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "gray",
            'steps': [
            {'range': [0, produced], 'color': '#F15014'},
            {'range': [produced, produced+remaining], 'color': '#9A224A'}],
            'threshold': {
                'line': {'color': "black", 'width': 4},
                'thickness': 0.75,
                'value': recoverable}}))

    return fig

def callback_reserves(selected_field):
    #get totalrecoverable and reserves
    df_info = field().get_field_reserves()
    df_info = df_info[df_info.fldName == selected_field]
    remaining_oil= float(df_info["fldRemainingOil"])
    remaining_gas= float(df_info["fldRemainingGas"])
    remaining_ngl= float(df_info["fldRemainingNGL"])
    remaining_condensate= float(df_info["fldRemainingCondensate"])


    fig={'data':[go.Pie(
        labels=["Oil","Gas","NGL","Condensate"],
        values = [remaining_oil,remaining_gas,remaining_ngl,remaining_condensate],
        title={'text': "Field Reserves"},
        marker={
                'colors':[
                    'rgb(36, 157, 32)',
                    'rgb(239, 34, 53)',
                    'rgb(239, 183, 34)',
                    'rgb(239, 34, 192)'
                ]
        },
        hole=0.4,
        hoverinfo="label+value"
        )],
        'layout': go.Layout(
            title='Reserves MOE'
        )}

    return fig

def callback_investments(selected_field):
    #get totalrecoverable and reserves
    df_info = field().get_field_investments()
    df_info = df_info[df_info.prfInformationCarrier == selected_field]
    df_info['prfInvestmentsMillNOK']=df_info['prfInvestmentsMillNOK'].astype('float')
    #print(df_info.head())


    fig={'data': [go.Bar(
        name="Yearly Investment MNOK",
        x = df_info.prfYear,
        y=df_info['prfInvestmentsMillNOK'],
        marker_line_color='rgb(8,48,107)',
        marker_line_width=1.5
        )],
        'layout': go.Layout(
            hovermode='closest',
            yaxis={'title':"Investments MNOK"},
            title="Investments"
        )}

    return fig
